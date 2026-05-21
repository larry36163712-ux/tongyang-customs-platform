# GitHub Releases 發布流程

Repository:

https://github.com/larry36163712-ux/tongyang-customs-platform

## 自動更新來源

正式版程式會讀取：

https://github.com/larry36163712-ux/tongyang-customs-platform/releases/latest/download/version.json

`version.json` 會指向同一個 Release 裡的 `default.exe`，並包含 SHA256。

## 發布第一個正式版本

1. 確認程式碼已推到 GitHub。
2. 到 GitHub repository 的 `Actions`。
3. 選擇 `Build and publish Windows EXE`。
4. 按 `Run workflow`。
5. 輸入版本號，例如 `1.0.0`。
6. 等待 workflow 完成。
7. 到 `Releases` 確認有兩個 asset：
   - `default.exe`
   - `version.json`

公司電腦上的舊版程式下次啟動或按「檢查更新」時，會自動檢查 GitHub Release，下載新版 EXE，覆蓋後重新啟動。

## 之後自動發布

第一個正式版本完成後，之後只要把程式碼 push 到 `main` 或 `master`，GitHub Actions 會自動：

1. 讀取 `settings.json` 的基礎版本。
2. 加上 GitHub Actions run number，形成新版號，例如 `1.0.0.25`。
3. 打包 `通洋報關平台.exe`。
4. 產生新版 `version.json`。
5. 建立 GitHub Release，並設為 latest。

公司端 EXE 啟動或按「檢查更新」時，會自動下載 latest release。

## 手動指定版本

若要指定明確版本，例如 `1.1.0`，請使用 `Actions` 裡的 `Run workflow`，輸入版本號 `1.1.0`。
