@echo off
setlocal
cd /d %~dp0

echo [INFO] 当前目录: %cd%

set "PYTHON=.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
  echo [ERROR] 未找到 %PYTHON%
  echo [HINT] 请先在当前目录(shp_buffer_tool)创建虚拟环境:
  echo            python -m venv .venv
  echo        然后:
  echo            .venv\Scripts\python.exe -m pip install --upgrade pip
  echo            .venv\Scripts\python.exe -m pip install -r requirements.txt
  goto :fail
)

echo [INFO] 使用解释器: %PYTHON%
"%PYTHON%" -V
if errorlevel 1 goto :fail

echo [STEP] 安装/校验依赖
"%PYTHON%" -m pip install --upgrade pip
if errorlevel 1 goto :fail
"%PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo [STEP] 调用 build.py 打包（默认 onefile）
"%PYTHON%" build.py %*
if errorlevel 1 goto :fail

echo.
echo [OK] 打包完成
echo [OUT] dist\shp-buffer-tool.exe
echo [NEXT] 把 dist 下的 exe 和 gui_config.example.yaml 一起拷给用户。
echo        首次启动会在 exe 同目录自动生成 gui_config.yaml。
pause
exit /b 0

:fail
echo.
echo [FAIL] 打包失败，请把上面报错截图给我
pause
exit /b 1
