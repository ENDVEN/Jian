# core/updater.py
import json
import urllib.request
from PyQt6.QtCore import QThread, pyqtSignal
from config import settings

class UpdateCheckerThread(QThread):
    """
    异步版本检测侦察兵。
    在后台静默请求云端配置，绝不卡顿 UI。
    """
    # 定义一个信号：当发现新版本时，将携带 (最新版本号, 更新说明, 下载链接) 发射回主线程
    update_available = pyqtSignal(str, str, str)
    
    def run(self):
        try:
            # 伪装成浏览器发起请求，并设置极短的超时时间(3秒)
            # 如果用户的网不好，3秒后自动放弃，当作没新版本处理，绝不死等
            req = urllib.request.Request(
                settings.UPDATE_CHECK_URL, 
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )
            with urllib.request.urlopen(req, timeout=3) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                # 如果是你用 Gitee API 获取的，内容可能在 'content' 字段并经过了 Base64 编码
                # 这里我们假设你直接访问的是一个纯净的 JSON 直链
                latest_version = data.get('version', '0.0.0')
                notes = data.get('notes', '发现新版本，建议更新。')
                download_url = data.get('url', '')
                
                # 比对版本号
                if self._is_newer(latest_version, settings.APP_VERSION):
                    # 发现新版本！发射信号！
                    self.update_available.emit(latest_version, notes, download_url)
                    
        except Exception as e:
            # 无论发生什么错误（断网、404、JSON解析失败），都在后台安静地死掉，不打扰用户
            pass
            
    def _is_newer(self, remote_ver: str, local_ver: str) -> bool:
        """比较版本号大小，例如 1.1.0 > 1.0.0"""
        try:
            r_parts = [int(x) for x in remote_ver.split('.')]
            l_parts = [int(x) for x in local_ver.split('.')]
            return r_parts > l_parts
        except Exception:
            return False