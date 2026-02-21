"""
增强转发服务 - Emby抢注终极优化版（2026-02-21）
优先直接转发（快+保留按钮）→ 失败再带自定义头部重发
"""

import os
import asyncio
from pathlib import Path
from typing import Optional, List, Dict

from telethon import TelegramClient
from telethon.errors import FloodWaitError, ChatForwardsRestrictedError, MediaEmptyError

from models import TelegramMessage, Account
from utils.singleton import Singleton
from utils.logger import get_logger


class EnhancedForwardService(metaclass=Singleton):
    
    def __init__(self):
        self.logger = get_logger(__name__)
        self.temp_downloads: Dict[str, str] = {}
        
        self.show_header = True
        self.show_monitor_name = True
        self.show_keywords = True
        self.show_link = True

    async def forward_message_enhanced(
        self,
        message: TelegramMessage,
        account: Account,
        target_ids: List[int],
        max_download_size_mb: Optional[float] = None,
        download_folder: str = "downloads",
        monitor_name: Optional[str] = None,
        matched_keywords: Optional[List[str]] = None
    ) -> Dict[int, bool]:
        results = {}
        client = account.client
        
        for target_id in target_ids:
            try:
                # 第一步：尝试直接转发（最快，完美保留按钮）
                success = await self._try_direct_forward(client, message, target_id)
                if success:
                    self.logger.info(f"✅ 直接转发成功（带按钮） → {target_id}")
                    results[target_id] = True
                    continue
                
                # 第二步：失败时走增强重发（带自定义头部）
                success = await self._download_and_resend(
                    client, message, target_id, max_download_size_mb, download_folder,
                    monitor_name, matched_keywords
                )
                results[target_id] = success
            except Exception as e:
                self.logger.error(f"转发到 {target_id} 失败: {e}")
                results[target_id] = False
        
        return results

    async def _try_direct_forward(self, client: TelegramClient, message: TelegramMessage, target_id: int) -> bool:
        """优先直接转发（最快，自动保留按钮）"""
        try:
            await client.forward_messages(target_id, [message.message_id], message.chat_id)
            return True
        except (ChatForwardsRestrictedError, MediaEmptyError):
            return False
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds)
            return False
        except Exception as e:
            self.logger.debug(f"直接转发失败: {e}")
            return False

    async def _build_source_header(
        self, client: TelegramClient, message: TelegramMessage,
        monitor_name: Optional[str] = None, matched_keywords: Optional[List[str]] = None
    ) -> str:
        if not self.show_header:
            return ""
        
        lines = ["📬 **Emby 监控提醒**"]
        
        if self.show_monitor_name and monitor_name:
            lines.append(f"🔍 **监控器**：{monitor_name}")
        
        try:
            entity = await client.get_entity(message.chat_id)
            title = getattr(entity, 'title', None) or getattr(entity, 'username', None) or f"ID:{message.chat_id}"
            if hasattr(entity, 'broadcast') and entity.broadcast:
                lines.append(f"📺 **源频道**：{title} (ID: {message.chat_id})")
            else:
                lines.append(f"📍 **源群组**：{title} (ID: {message.chat_id})")
        except:
            lines.append(f"📍 **源群组**：ID {message.chat_id}")
        
        sender = ""
        if message.sender and getattr(message.sender, 'full_name', None):
            sender = f"👤 {message.sender.full_name} "
        time_str = message.timestamp.strftime('%H:%M:%S')
        lines.append(f"{sender}⏰ {time_str}")
        
        if self.show_keywords and matched_keywords:
            kw_str = " | ".join([f"**{kw}**" for kw in matched_keywords])
            if any(k in " ".join(matched_keywords).lower() for k in ["emby", "注册", "邀请", "开注"]):
                lines.append(f"🎯 **匹配**：📬 {kw_str}")
            else:
                lines.append(f"🎯 **匹配**：{kw_str}")
        
        if self.show_link:
            try:
                chat_str = str(message.chat_id)
                if chat_str.startswith('-100'):
                    clean_id = chat_str[4:]
                    link = f"https://t.me/c/{clean_id}/{message.message_id}"
                    lines.append(f"🔗 **源消息**：{link}")
            except:
                pass
        
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines) + "\n"

    async def _download_and_resend(self, client, message, target_id, max_size, folder, monitor_name=None, matched_keywords=None):
        try:
            original = await client.get_messages(message.chat_id, ids=message.message_id)
            
            if original and original.media is not None:
                return await self._download_and_send_media(
                    client, message, target_id, folder, monitor_name, matched_keywords, original
                )
            else:
                return await self._send_text_message(
                    client, message, target_id, monitor_name, matched_keywords, original
                )
        except Exception as e:
            self.logger.error(f"重发失败: {e}")
            return False

    async def _download_and_send_media(self, client, message, target_id, folder, monitor_name, matched_keywords, original):
        downloaded_path = None
        try:
            file_name = getattr(message.media, 'file_name', None) or f"file_{message.message_id}"
            file_path = Path(folder) / file_name
            
            downloaded_path = await original.download_media(file=str(file_path))
            if not downloaded_path:
                return False
            
            header = await self._build_source_header(client, message, monitor_name, matched_keywords)
            caption = header + (message.text or "【纯媒体消息】")
            
            await client.send_file(
                target_id,
                str(downloaded_path),
                caption=caption,
                reply_markup=original.reply_markup   # 保留按钮
            )
            return True
        finally:
            if downloaded_path and os.path.exists(downloaded_path):
                try: os.remove(downloaded_path)
                except: pass

    async def _send_text_message(self, client, message, target_id, monitor_name, matched_keywords, original):
        try:
            if message.text:
                header = await self._build_source_header(client, message, monitor_name, matched_keywords)
                full_text = header + message.text
                
                await client.send_message(
                    target_id,
                    full_text,
                    parse_mode='markdown',
                    reply_markup=original.reply_markup if original else None   # 保留按钮
                )
                return True
            return False
        except Exception as e:
            self.logger.error(f"文本重发失败: {e}")
            return False
