@echo off
rem Builds bin\dmcombat.vtm (Win32 DLL, static CRT). Run from DMCombat_dev (a path without spaces, e.g. a subst drive).
rem Needs Visual Studio 2017+ or its Build Tools with "Desktop development with C++"; found with vswhere (offline).
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
set "VCVARS="
if exist "%VSWHERE%" for /f "usebackq delims=" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VCVARS=%%i\VC\Auxiliary\Build\vcvarsall.bat"
if not defined VCVARS set "VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"
if not exist "%VCVARS%" (echo Visual C++ build tools not found - install Visual Studio Build Tools with "Desktop development with C++" & exit /b 1)
call "%VCVARS%" x86 >nul || exit /b 1
if not exist bin mkdir bin
if not exist obj mkdir obj
cl /nologo /O2 /MT /EHsc /W3 /D_CRT_SECURE_NO_WARNINGS /Foobj\ src\dmcombat\*.cpp /LD /link /DEF:src\dmcombat\dmcombat.def /OUT:bin\dmcombat.vtm /IMPLIB:obj\dmcombat.lib user32.lib || exit /b 1
echo BUILD OK
