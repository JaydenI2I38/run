"""GUI / exe 版缓冲区判定工具的服务层。

特点：
- 自包含，不依赖父级 ``lib`` 包，方便 PyInstaller 打包。
- 配置中的相对路径以 ``gui_config.yaml`` 所在目录为基准解析，
  这样把 exe + yaml + shp_input + output 一起放到任何位置都能跑。
- 点位判定使用 shapely 2.x 的向量化 API，比 Python 循环快数十倍。
"""
from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

import numpy as np
import pandas as pd
import shapefile
import shapely
import yaml
from shapely.geometry import shape
from shapely.ops import unary_union

log = logging.getLogger(__name__)
ProgressCallback = Callable[[str, "float | None"], None]

NAME_KEYS: tuple[str, ...] = ("monitor_name", "name", "名称")
LNG_KEYS: tuple[str, ...] = ("longitude", "lng", "lon", "经度")
LAT_KEYS: tuple[str, ...] = ("latitude", "lat", "纬度")


@dataclass
class ProvinceItem:
    code: str
    name: str

    @property
    def label(self) -> str:
        return f"{self.name} ({self.code})"


@dataclass
class GuiToolConfig:
    """GUI 配置。所有路径字段都已展开成绝对路径。"""

    shp_root_dir: Path
    output_dir: Path
    flag_column: str = "是否在缓冲区内"
    filename_code_regex: str = r"(\d{6})"
    output_name_template: str = "{excel_stem}_{province_code}_{province_name}_flagged.xlsx"
    provinces: list[ProvinceItem] = field(default_factory=list)
    config_path: Path | None = None  # 用于回写

    def find_province(self, code_or_label: str) -> ProvinceItem:
        for p in self.provinces:
            if code_or_label in (p.code, p.name, p.label):
                return p
        raise ValueError(f"未找到省份: {code_or_label}")


@dataclass
class PointInput:
    df: pd.DataFrame
    lng_col: str
    lat_col: str
    coords: np.ndarray  # (N, 2) [lng, lat]


@dataclass
class RunResult:
    province_code: str
    province_name: str
    shp_paths: list[Path]
    output_path: Path
    total_rows: int
    hit_count: int


@dataclass
class ProgressLogger:
    callback: ProgressCallback | None = None

    def emit(self, message: str, percent: float | None = None) -> None:
        log.info(message)
        if self.callback:
            self.callback(message, percent)


# ---------------------------------------------------------------------------
# 路径与配置
# ---------------------------------------------------------------------------


def app_base_dir() -> Path:
    """返回"应用所在目录"。

    - 打包后（PyInstaller onefile / onedir）返回 exe 旁的目录；
    - 源码运行时返回 ``service.py`` 所在目录。
    用于解析配置文件中的相对路径。
    """
    if getattr(sys, "frozen", False):  # PyInstaller
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _resolve_path(value: str, base: Path) -> Path:
    p = Path(str(value)).expanduser()
    if not p.is_absolute():
        p = (base / p).resolve()
    else:
        p = p.resolve()
    return p


def load_gui_config(path: str | Path) -> GuiToolConfig:
    cfg_path = Path(path).expanduser().resolve()
    if not cfg_path.exists():
        raise FileNotFoundError(f"GUI 配置文件不存在: {cfg_path}")
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

    base = cfg_path.parent
    try:
        shp = raw["shp"]
        out = raw["output"]
        shp_root_dir = _resolve_path(shp["root_dir"], base)
        output_dir = _resolve_path(out["dir"], base)
        flag_column = str(out.get("flag_column") or "是否在缓冲区内")
        output_name_template = str(
            out.get("filename_template")
            or "{excel_stem}_{province_code}_{province_name}_flagged.xlsx"
        )
        filename_code_regex = str(shp.get("filename_code_regex") or r"(\d{6})")
        provinces = [
            ProvinceItem(code=str(item["code"]), name=str(item["name"]))
            for item in (raw.get("region") or {}).get("provinces", [])
        ]
    except KeyError as e:
        raise ValueError(f"GUI 配置缺少必填字段: {e}") from e

    if not provinces:
        raise ValueError("GUI 配置中的 region.provinces 不能为空")

    return GuiToolConfig(
        shp_root_dir=shp_root_dir,
        output_dir=output_dir,
        flag_column=flag_column,
        filename_code_regex=filename_code_regex,
        output_name_template=output_name_template,
        provinces=provinces,
        config_path=cfg_path,
    )


def list_provinces(cfg: GuiToolConfig) -> list[ProvinceItem]:
    return list(cfg.provinces)


# ---------------------------------------------------------------------------
# Excel 读取
# ---------------------------------------------------------------------------


def _resolve_column(df: pd.DataFrame, candidates: Sequence[str], override: str | None) -> str | None:
    if override:
        if override in df.columns:
            return override
        for col in df.columns:
            if str(col).strip().lower() == override.strip().lower():
                return col
        raise ValueError(f"指定列不存在: {override}；可用列: {list(df.columns)}")
    lower_map = {str(c).strip().lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in lower_map:
            return lower_map[cand.lower()]
    return None


def read_points(
    excel_path: str | Path,
    *,
    sheet: int | str = 0,
    field_overrides: dict[str, str] | None = None,
) -> PointInput:
    path = Path(excel_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"点位 Excel 不存在: {path}")

    sheet_arg: int | str = sheet if sheet not in (None, "") else 0
    df = pd.read_excel(path, sheet_name=sheet_arg, dtype=object)
    log.info("读取 Excel %s，行数=%d，列=%s", path, len(df), list(df.columns))

    overrides = field_overrides or {}
    lng_col = _resolve_column(df, LNG_KEYS, overrides.get("longitude"))
    lat_col = _resolve_column(df, LAT_KEYS, overrides.get("latitude"))

    missing = [k for k, v in (("longitude", lng_col), ("latitude", lat_col)) if v is None]
    if missing:
        raise ValueError(
            f"Excel 缺少必填列: {missing}；可用列: {list(df.columns)}；"
            "可在 GUI 中通过『高级…』指定列名。"
        )
    assert lng_col and lat_col

    lng = pd.to_numeric(df[lng_col], errors="coerce")
    lat = pd.to_numeric(df[lat_col], errors="coerce")
    bad = lng.isna() | lat.isna() | (lng < -180) | (lng > 180) | (lat < -90) | (lat > 90)
    if bad.any():
        bad_lines = (np.where(bad.to_numpy())[0] + 2).tolist()  # +2: 表头 + 1-based
        raise ValueError(
            "经纬度非法或超出范围（WGS84，需 lng∈[-180,180], lat∈[-90,90]），"
            f"问题行号(Excel 行号)前 10 个: {bad_lines[:10]}"
        )

    coords = np.stack(
        [lng.to_numpy(dtype=np.float64), lat.to_numpy(dtype=np.float64)], axis=1
    )
    return PointInput(df=df, lng_col=lng_col, lat_col=lat_col, coords=coords)


# ---------------------------------------------------------------------------
# Shp 加载与匹配
# ---------------------------------------------------------------------------


def find_matching_shp_paths(cfg: GuiToolConfig, province_code: str) -> list[Path]:
    root = Path(cfg.shp_root_dir).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"shp 根目录不存在: {root}")

    pattern = re.compile(cfg.filename_code_regex)
    matches: list[Path] = []
    for path in sorted(root.rglob("*.shp")):
        codes = [c for c in pattern.findall(path.name) if len(c) == 6]
        if province_code in codes:
            matches.append(path)
    if not matches:
        raise FileNotFoundError(
            f"未在 {root} 中匹配到省份编码 {province_code} 对应的 shp"
        )
    return matches


def load_buffer_union(
    shp_paths: Iterable[str | Path], progress: ProgressLogger | None = None
):
    paths = [Path(p).expanduser().resolve() for p in shp_paths]
    if not paths:
        raise ValueError("未提供任何 shp 路径")

    geoms = []
    total = len(paths)
    for idx, path in enumerate(paths, start=1):
        if not path.exists():
            raise FileNotFoundError(f"缓冲区 shp 不存在: {path}")
        if progress:
            progress.emit(
                f"读取 shp {idx}/{total}: {path.name}",
                10 + 30 * idx / max(total, 1),
            )
        reader = shapefile.Reader(str(path), encoding="utf-8")
        for shp in reader.shapes():
            if not shp.points:
                continue
            geom = shape(shp.__geo_interface__)
            if geom.is_empty:
                continue
            geoms.append(geom)

    if not geoms:
        raise ValueError("所有 shp 中都未读取到有效面要素")
    if progress:
        progress.emit(f"开始合并 {len(geoms)} 个面要素", 45)
    return unary_union(geoms)


# ---------------------------------------------------------------------------
# 判定
# ---------------------------------------------------------------------------


def flag_points_in_buffer(
    coords: np.ndarray,
    buffer_geom,
    progress: ProgressLogger | None = None,
) -> np.ndarray:
    """向量化点-面包含判定。

    使用 shapely 2.x 的 ``contains_xy``，C 层一次性处理全部点，比
    Python 循环 + ``prepared.covers`` 快数十倍。
    """
    if coords.size == 0:
        return np.zeros(0, dtype=bool)
    if progress:
        progress.emit(f"开始判定 {coords.shape[0]} 个点位", 50)
    # contains_xy 在 shapely 2.x 中存在；若用户使用更旧版本，回退到 vectorized
    contains_xy = getattr(shapely, "contains_xy", None)
    x = coords[:, 0]
    y = coords[:, 1]
    if contains_xy is not None:
        mask = contains_xy(buffer_geom, x, y)
    else:  # 兼容老版本
        from shapely.vectorized import contains as _v_contains  # type: ignore

        mask = _v_contains(buffer_geom, x, y)
    if progress:
        progress.emit("点位判定完成", 88)
    return np.asarray(mask, dtype=bool)


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------


def build_output_path(
    cfg: GuiToolConfig,
    excel_path: str | Path,
    province: ProvinceItem,
    *,
    output_dir_override: str | Path | None = None,
) -> Path:
    output_dir = Path(output_dir_override or cfg.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    excel_stem = Path(excel_path).stem
    filename = cfg.output_name_template.format(
        excel_stem=excel_stem,
        province_code=province.code,
        province_name=province.name,
    )
    return output_dir / filename


def process_excel_with_province(
    cfg: GuiToolConfig,
    province: ProvinceItem,
    excel_path: str | Path,
    *,
    sheet: int | str = 0,
    field_overrides: dict[str, str] | None = None,
    output_dir_override: str | Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> RunResult:
    progress = ProgressLogger(progress_callback)
    progress.emit("开始扫描 shp 目录", 0)
    shp_paths = find_matching_shp_paths(cfg, province.code)
    progress.emit(f"匹配到 {len(shp_paths)} 个 shp", 5)

    progress.emit("开始读取 Excel", 8)
    point_input = read_points(
        excel_path, sheet=sheet, field_overrides=field_overrides
    )
    progress.emit(f"Excel 读取完成，共 {len(point_input.df)} 行", 10)

    buffer_geom = load_buffer_union(shp_paths, progress)
    flag = flag_points_in_buffer(point_input.coords, buffer_geom, progress)

    output_path = build_output_path(
        cfg, excel_path, province, output_dir_override=output_dir_override
    )
    progress.emit("开始写出 Excel", 92)
    result_df = point_input.df.copy()
    result_df[cfg.flag_column] = flag.astype(bool)
    result_df.to_excel(output_path, index=False)

    hit_count = int(flag.sum())
    progress.emit(
        f"完成，命中 {hit_count}/{len(result_df)}，输出：{output_path}", 100
    )
    return RunResult(
        province_code=province.code,
        province_name=province.name,
        shp_paths=shp_paths,
        output_path=output_path,
        total_rows=len(result_df),
        hit_count=hit_count,
    )
