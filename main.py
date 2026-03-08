from pathlib import Path
from typing import Dict, Optional

from astrbot.api.star import Context, Star
from astrbot.api.event import (
    AstrMessageEvent,
    MessageChain,
    filter,
    EventMessageType   # 必须导入这个枚举
)
from astrbot.api.message_components import Record
from astrbot.api import logger

class VoiceDaka(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.voice_dir = Path(__file__).parent / "voices"
        self.voice_map: Dict[str, str] = {}
        self._load_voices()

    def _load_voices(self):
        if not self.voice_dir.exists():
            self.voice_dir.mkdir(parents=True, exist_ok=True)
            logger.info("[VoiceDaka] voices 目录已创建，请放入音频文件后重载插件")
            return

        count = 0
        for file in self.voice_dir.iterdir():
            if file.is_file():
                ext = file.suffix.lower()
                if ext in {".silk", ".amr", ".ogg", ".mp3", ".wav"}:
                    keyword = file.stem.strip()
                    abs_path = str(file.absolute())
                    self.voice_map[keyword] = abs_path
                    count += 1
                    logger.debug(f"[VoiceDaka] 加载: '{keyword}' → {abs_path} ({ext})")

        if count > 0:
            logger.info(f"[VoiceDaka] 加载完成：{count} 个语音文件")
            logger.info(f"[VoiceDaka] 关键词: {', '.join(sorted(self.voice_map.keys()))}")
        else:
            logger.warning("[VoiceDaka] 无有效音频文件")

    # 修复核心：用这个装饰器监听所有消息
    @filter.event_message_type(EventMessageType.ALL)
    async def on_all_message(self, event: AstrMessageEvent):
        if event.message_str is None:
            logger.debug("[VoiceDaka] 无文本消息，跳过")
            return False

        text = event.message_str.strip()
        logger.debug(f"[VoiceDaka] 收到消息: '{text}' (原始: '{event.message_str}')")

        if not text:
            return False

        matched_path: Optional[str] = self.voice_map.get(text)

        # 可选：支持“消息包含关键词”而不是严格等于
        if matched_path is None:
            for kw, path in self.voice_map.items():
                if kw in text:
                    matched_path = path
                    logger.debug(f"[VoiceDaka] 包含匹配: '{kw}' 在 '{text}'")
                    break

        if matched_path is None:
            logger.debug(f"[VoiceDaka] 未匹配: '{text}'")
            return False

        try:
            logger.info(f"[VoiceDaka] 发送语音: '{text}' → {matched_path}")
            chain = MessageChain()
            chain.append(Record(file=matched_path))
            await event.reply(chain)
            logger.info("[VoiceDaka] 发送成功")
            return True   # 已处理，拦截

        except Exception as e:
            logger.error(f"[VoiceDaka] 发送失败: {str(e)}", exc_info=True)
            await event.reply(f"语音发送出错（建议转 .wav 格式）：{str(e)}")
            return True
