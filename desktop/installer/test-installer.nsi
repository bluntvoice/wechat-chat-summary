Unicode true

!include "MUI2.nsh"

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
InstallDir "$LOCALAPPDATA\Programs\WeChat Chat Summary"
InstallDirRegKey HKCU "Software\bluntvoice\WeChatChatSummary" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 64
ShowInstDetails show
ShowUninstDetails show

VIProductVersion "${FILE_VERSION}"
VIAddVersionKey /LANG=2052 "ProductName" "微信群聊总结"
VIAddVersionKey /LANG=2052 "FileDescription" "${FILE_DESCRIPTION}"
VIAddVersionKey /LANG=2052 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=2052 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=2052 "CompanyName" "bluntvoice"
VIAddVersionKey /LANG=2052 "LegalCopyright" "Copyright bluntvoice"

!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\program\WeChat Chat Summary.exe"
!define MUI_FINISHPAGE_RUN_TEXT "启动微信群聊总结"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"

Section "主程序" SEC_MAIN
  ; program 是安装器唯一拥有并可递归替换的目录。
  RMDir /r "$INSTDIR\program"
  SetOutPath "$INSTDIR\program"
  File "/oname=WeChat Chat Summary.exe" "${APP_EXE}"

  SetOutPath "$INSTDIR\program\engine"
  File /r "${ENGINE_DIR}\*"

  SetOutPath "$INSTDIR"
  ; 清理旧测试安装包的单个入口文件，不递归删除旧根目录或用户文件。
  Delete "$INSTDIR\WeChat Chat Summary.exe"
  WriteUninstaller "$INSTDIR\卸载微信群聊总结.exe"
  WriteRegStr HKCU "Software\bluntvoice\WeChatChatSummary" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\WeChatChatSummary" "DisplayName" "${PRODUCT_NAME}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\WeChatChatSummary" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\WeChatChatSummary" "Publisher" "bluntvoice"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\WeChatChatSummary" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\WeChatChatSummary" "UninstallString" '"$INSTDIR\卸载微信群聊总结.exe"'
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\WeChatChatSummary" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\WeChatChatSummary" "NoRepair" 1

  CreateDirectory "$SMPROGRAMS\微信群聊总结"
  CreateShortcut "$SMPROGRAMS\微信群聊总结\微信群聊总结.lnk" "$INSTDIR\program\WeChat Chat Summary.exe"
  CreateShortcut "$SMPROGRAMS\微信群聊总结\卸载微信群聊总结.lnk" "$INSTDIR\卸载微信群聊总结.exe"
  CreateShortcut "$DESKTOP\微信群聊总结.lnk" "$INSTDIR\program\WeChat Chat Summary.exe"
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\微信群聊总结.lnk"
  Delete "$SMPROGRAMS\微信群聊总结\微信群聊总结.lnk"
  Delete "$SMPROGRAMS\微信群聊总结\卸载微信群聊总结.lnk"
  RMDir "$SMPROGRAMS\微信群聊总结"

  Delete "$INSTDIR\WeChat Chat Summary.exe"
  Delete "$INSTDIR\卸载微信群聊总结.exe"
  RMDir /r "$INSTDIR\program"
  RMDir "$INSTDIR"

  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\WeChatChatSummary"
  DeleteRegKey HKCU "Software\bluntvoice\WeChatChatSummary"
SectionEnd
