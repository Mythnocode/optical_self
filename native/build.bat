@echo off
rem 编译原生多线程光线追迹内核（MinGW-w64 g++）。
rem 产物: native\build\optical_native.dll
rem Python 侧在光学引擎启动时自动加载；缺失时自动回退纯 Python 追迹。
rem 环境变量 OPTICAL_NATIVE_DLL 可覆盖 DLL 路径，OPTICAL_NATIVE_THREADS
rem 覆盖线程数（默认自动），OPTICAL_NATIVE=0 强制关闭原生路径。

if not exist build mkdir build
g++ -O2 -std=c++17 -shared -static-libgcc -static-libstdc++ ^
  -o build\optical_native.dll optical_native_core.cpp ^
  -Wall -Wno-unused-parameter
if errorlevel 1 (
  echo build FAILED
  exit /b 1
)
echo build OK: native\build\optical_native.dll
