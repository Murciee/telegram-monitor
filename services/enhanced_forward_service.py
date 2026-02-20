"""
增强转发服务 - 终极进阶版（已集成你所有需求）
来源头部 + 监控器名称 + 关键词高亮 + 可配置开关
"""

import os
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any

from telethon import TelegramClient
from telethon.errors import FloodWaitError, ChatForwardsRestrictedError, MediaEmptyError

from models import TelegramMessage, Account
from utils.singleton import Singleton
from utils.logger import get_logger


class EnhancedForwardService(metaclass=Singleton):
    
    def __init__(self):
        self.logger = get_logger(__name__)
        self.temp_downloads: Dict[str, str] = {}
        
        # ================== 可配置开关（推荐在 web_app.py 里调用 set_config） ==================
        self.show_source_header: bool = True      # 显示整个头部
        self.show_monitor_name: bool = True       # 显示监控器名称（如 Emby注册码监控）
        self.show_matched_keywords: bool = True   # 高亮匹配到的关键词
        # =================================================================================
    
    def set_config(self, show_header: bool = None, show_monitor: bool = None, show_keywords: bool = None):
        if show_header is not None: self.show_source_header = show_header
        if show_monitor is not None: self.show_monitor_name = show_monitor
        if show_keywords is not None: self.show_matched_keywords = show_keywords
        self.logger.info(f"转发配置更新 → header:{self.show_source_header} monitor:{self.show_monitor_name} keywords:{self.show_matched_keywords}")

    async def forward_message_enhanced(
        self,
        message: TelegramMessage,
        account: Account,
        target_ids: List[int],
        max_download_size_mb: Optional[float] = None,
        download_folder: str = "downloads",
        monitor_name: Optional[str] = None,           # 新增
        matched_keywords: Optional[List[str]] = None  # 新增
    ) -> Dict[int, bool]:
        results = {}
        client = account.client
        
        for target_id in target_ids:
            try:
                success = await self._try_direct_forward(client, message, target_id)
                if success:
                    results[target_id] = True
                    continue
                
                success = await self._download_and_resend(
                    client, message, target_id, max_download_size_mb, download_folder,
                    monitor_name, matched_keywords
                )
                results[target_id] = success
                
            except Exception as e:
                self.logger.error(f"转发到 {target_id} 失败: {e}")
                results[target_id] = False
        
        return results

    async def _build_source_header(
        self, 
        client: TelegramClient, 
        message: TelegramMessage,
        monitor_name: Optional[str] = None,
        matched_keywords: Optional[List[str]] = None
    ) -> str:
        if not self.show_source_header:
            return ""
        
        header = ["📌 **监控消息提醒**"]
        
        if self.show_monitor_name and monitor_name:
            header.append(f"🔍 **监控器**: {monitor_name}")
        
        # 来源群组
        try:
            entity = await client.get_entity(message.chat_id)
            title = getattr(entity, 'title', None) or getattr(entity, 'username', f"ID:{message.chat_id}")
            header.append(f"📍 **来源**: {title}")
        except:
            header.append(f"📍 **来源群组ID**: {message.chat_id}")
        
        # 发送者
        if message.sender and getattr(message.sender, 'full_name', None):
            header.append(f"👤 **发送者**: {message.sender.full_name} (ID: {message.sender.id})")
        
        # 原始链接
        try:
            chat_str = str(message.chat_id)
            if chat_str.startswith('-100'):
                link = f"https://t.me/c/{chat_str[4:]}/{message.message_id}"
                header.append(f"🔗 **原始链接**: {link}")
        except:
            pass
        
        header.append(f"⏰ **时间**: {message.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # 高亮关键词
        if self.show_matched_keywords and matched_keywords and matched_keywords:
            kw_str = " | ".join([f"**{k}**" for k in matched_keywords])
            header.append(f"🎯 **匹配关键词**: {kw_str}")
        
        header.append("─" * 35 + "\n")
        return "\n".join(header)

    # 以下 3 个方法只改了参数传递和 header 调用（其他保持原项目逻辑）
    async def _try_direct_forward(self, client: TelegramClient, message: TelegramMessage, target_id: int) -> bool:
        try:
            await client.forward_messages(target_id, [message.message_id], message.chat_id)
            return True
        except (ChatForwardsRestrictedError, MediaEmptyError):
            return False
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds)
            return False
        except Exception as e:
            self.logger.error(f"直接转发失败: {e}")
            return False

    async def _download_and_resend(self, client, message, target_id, max_size, folder, monitor_name=None, matched_keywords=None):
        try:
            if message.media and message.media.file_size_mb and max_size and message.media.file_size_mb > max_size:
                return False
            
            download_path = Path(folder)
            download_path.mkdir(parents=True, exist_ok=True)
            
            if message.media and message.media.has_media:
                return await self._download_and_send_media(client, message, target_id, download_path, monitor_name, matched_keywords)
            else:
                return await self._send_text_message(client, message, target_id, monitor_name, matched_keywords)
        except Exception as e:
            self.logger.error(f"下载重发失败: {e}")
            return False

    async def _download_and_send_media(self, client, message, target_id, download_path, monitor_name=None, matched_keywords=None):
        downloaded_path = None
        try:
            original = await client.get_messages(message.chat_id, ids=message.message_id)
            if not original or not original.media: return False
            
            file_name = getattr(message.media, 'file_name', None) or f"file_{message.message_id}"
            file_path = download_path / file_name
            
            downloaded_path = await original.download_media(file=str(file_path))
            if not downloaded_path: return False
            
            header = await self._build_source_header(client, message, monitor_name, matched_keywords)
            caption = header + (message.text or "【纯媒体消息】")
            
            await client.send_file(target_id, str(downloaded_path), caption=caption)
            return True
        finally:
            if downloaded_path and os.path.exists(downloaded_path):
                try: os.remove(downloaded_path)
                except: pass

    async def _send_text_message(self, client, message, target_id, monitor_name=None, matched_keywords=None):
        try:
            if message.text:
                header = await self._build_source_header(client, message, monitor_name, matched_keywords)
                await client.send_message(target_id, header + message.text, parse_mode='markdown')
                return True
            return False
        except Exception as e:
            self.logger.error(f"文本重发失败: {e}")
            return False
