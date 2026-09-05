Unicode true

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "WinMessages.nsh"

!define APP_RUNNING_MUTEX "Local\bluntvoice.wechat-chat-summary.app-running"
!define APP_CLOSE_WAIT_STEPS 40

!ifndef APP_EXE
  !error "APP_EXE is required"
!endif
!ifndef ENGINE_DIR
  !error "ENGINE_DIR is required"
!endif
!ifndef OUTPUT_FILE
  !error "OUTPUT_FILE is required"
!endif
!ifndef VERSION
  !error "VERSION is required"
!endif
!ifndef FILE_VERSION
  !error "FILE_VERSION is required"
!endif
!ifndef PRODUCT_NAME
  !error "PRODUCT_NAME is required"
!endif
!ifndef FILE_DESCRIPTION
  !error "FILE_DESCRIPTION is required"
!endif

Name "${PRODUCT_NAME}"
OutFile "${OUTPUT_FILE}"
InstallDir "$LOCALAPPDATA\Programs\群聊拾遗"
InstallDirRegKey HKCU "Software\bluntvoice\WeChatChatSummary" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 64
ShowInstDetails show
ShowUninstDetails show

VIProductVersion "${FILE_VERSION}"
VIAddVersionKey /LANG=2052 "ProductName" "${PRODUCT_NAME}"
VIAddVersionKey /LANG=2052 "FileDescription" "${FILE_DESCRIPTION}"
VIAddVersionKey /LANG=2052 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=2052 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=2052 "CompanyName" "bluntvoice"
VIAddVersionKey /LANG=2052 "LegalCopyright" "Copyright bluntvoice"

!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\program\群聊拾遗.exe"
!define MUI_FINISHPAGE_RUN_TEXT "启动群聊拾遗"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"

Function RequestAppClose
  FindWindow $1 "" "${PRODUCT_NAME}"
  ${If} $1 != 0
    SendMessage $1 ${WM_CLOSE} 0 0 /TIMEOUT=2000
  ${EndIf}

  StrCpy $2 0
wait_for_close:
  Sleep 250
  StrCpy $0 0
  System::Call 'kernel32::OpenMutexW(i 0x00100000, i 0, w "${APP_RUNNING_MUTEX}") p .r0'
  ${If} $0 == 0
    Return
  ${EndIf}
  System::Call 'kernel32::CloseHandle(p r0)'
  IntOp $2 $2 + 1
  IntCmp $2 ${APP_CLOSE_WAIT_STEPS} close_timeout wait_for_close close_timeout
close_timeout:
FunctionEnd

Function EnsureAppClosed
check_app:
  StrCpy $0 0
  System::Call 'kernel32::OpenMutexW(i 0x00100000, i 0, w "${APP_RUNNING_MUTEX}") p .r0'
  ${If} $0 != 0
    System::Call 'kernel32::CloseHandle(p r0)'
    Call RequestAppClose
    StrCpy $0 0
    System::Call 'kernel32::OpenMutexW(i 0x00100000, i 0, w "${APP_RUNNING_MUTEX}") p .r0'
    ${If} $0 != 0
      System::Call 'kernel32::CloseHandle(p r0)'
      MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "群聊拾遗未能自动正常关闭。$\r$\n$\r$\n请确认软件中的任务已经结束并手动关闭，再点击重试继续安装；点击取消将退出安装。" IDRETRY check_app IDCANCEL cancel_install
    ${EndIf}
  ${EndIf}
  Return
cancel_install:
  Abort
FunctionEnd

Function .onInit
  Call EnsureAppClosed
FunctionEnd

Function un.RequestAppClose
  FindWindow $1 "" "${PRODUCT_NAME}"
  ${If} $1 != 0
    SendMessage $1 ${WM_CLOSE} 0 0 /TIMEOUT=2000
  ${EndIf}

  StrCpy $2 0
wait_for_close:
  Sleep 250
  StrCpy $0 0
  System::Call 'kernel32::OpenMutexW(i 0x00100000, i 0, w "${APP_RUNNING_MUTEX}") p .r0'
  ${If} $0 == 0
    Return
  ${EndIf}
  System::Call 'kernel32::CloseHandle(p r0)'
  IntOp $2 $2 + 1
  IntCmp $2 ${APP_CLOSE_WAIT_STEPS} close_timeout wait_for_close close_timeout
close_timeout:
FunctionEnd

Function un.EnsureAppClosed
check_app:
  StrCpy $0 0
  System::Call 'kernel32::OpenMutexW(i 0x00100000, i 0, w "${APP_RUNNING_MUTEX}") p .r0'
  ${If} $0 != 0
    System::Call 'kernel32::CloseHandle(p r0)'
    Call un.RequestAppClose
    StrCpy $0 0
    System::Call 'kernel32::OpenMutexW(i 0x00100000, i 0, w "${APP_RUNNING_MUTEX}") p .r0'
    ${If} $0 != 0
      System::Call 'kernel32::CloseHandle(p r0)'
      MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "群聊拾遗未能自动正常关闭。$\r$\n$\r$\n请确认软件中的任务已经结束并手动关闭，再点击重试继续卸载；点击取消将退出卸载。" IDRETRY check_app IDCANCEL cancel_uninstall
    ${EndIf}
  ${EndIf}
  Return
cancel_uninstall:
  Abort
FunctionEnd

Function un.onInit
  Call un.EnsureAppClosed
FunctionEnd

Section "主程序" SEC_MAIN
  ; 用户可能在欢迎页停留期间重新启动软件，替换 program 前再次确认。
  Call EnsureAppClosed
  ; program 是安装器唯一拥有并可递归替换的目录。
  RMDir /r "$INSTDIR\program"
  SetOutPath "$INSTDIR\program"
  File "/oname=群聊拾遗.exe" "${APP_EXE}"

  SetOutPath "$INSTDIR\program\engine"
  File /r "${ENGINE_DIR}\*"

  SetOutPath "$INSTDIR"
  ; 清理旧测试安装包的单个入口文件，不递归删除旧根目录或用户文件。
  Delete "$INSTDIR\WeChat Chat Summary.exe"
  Delete "$INSTDIR\卸载微信群聊总结.exe"
  Delete "$DESKTOP\微信群聊总结.lnk"
  Delete "$SMPROGRAMS\微信群聊总结\微信群聊总结.lnk"
  Delete "$SMPROGRAMS\微信群聊总结\卸载微信群聊总结.lnk"
  RMDir "$SMPROGRAMS\微信群聊总结"
  WriteUninstaller "$INSTDIR\卸载群聊拾遗.exe"
  WriteRegStr HKCU "Software\bluntvoice\WeChatChatSummary" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\WeChatChatSummary" "DisplayName" "${PRODUCT_NAME}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\WeChatChatSummary" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\WeChatChatSummary" "Publisher" "bluntvoice"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\WeChatChatSummary" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\WeChatChatSummary" "UninstallString" '"$INSTDIR\卸载群聊拾遗.exe"'
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\WeChatChatSummary" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\WeChatChatSummary" "NoRepair" 1

  CreateDirectory "$SMPROGRAMS\群聊拾遗"
  CreateShortcut "$SMPROGRAMS\群聊拾遗\群聊拾遗.lnk" "$INSTDIR\program\群聊拾遗.exe"
  CreateShortcut "$SMPROGRAMS\群聊拾遗\卸载群聊拾遗.lnk" "$INSTDIR\卸载群聊拾遗.exe"
  CreateShortcut "$DESKTOP\群聊拾遗.lnk" "$INSTDIR\program\群聊拾遗.exe"
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\群聊拾遗.lnk"
  Delete "$SMPROGRAMS\群聊拾遗\群聊拾遗.lnk"
  Delete "$SMPROGRAMS\群聊拾遗\卸载群聊拾遗.lnk"
  RMDir "$SMPROGRAMS\群聊拾遗"

  ; 兼容清理更名前的测试安装包快捷方式。
  Delete "$DESKTOP\微信群聊总结.lnk"
  Delete "$SMPROGRAMS\微信群聊总结\微信群聊总结.lnk"
  Delete "$SMPROGRAMS\微信群聊总结\卸载微信群聊总结.lnk"
  RMDir "$SMPROGRAMS\微信群聊总结"

  Delete "$INSTDIR\WeChat Chat Summary.exe"
  Delete "$INSTDIR\卸载群聊拾遗.exe"
  Delete "$INSTDIR\卸载微信群聊总结.exe"
  RMDir /r "$INSTDIR\program"
  RMDir "$INSTDIR"

  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\WeChatChatSummary"
  DeleteRegKey HKCU "Software\bluntvoice\WeChatChatSummary"
SectionEnd
