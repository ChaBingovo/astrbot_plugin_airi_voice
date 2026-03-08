from pathlib import Path
from typing import Dict, Optional

from astrbot.api.star import Context, Star
from astrbot.api.event import AstrMessageEvent, MessageChain
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
            logger.info("[VoiceDaka] 创建 voices 目录")
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
                    logger.debug(f"[VoiceDaka] 加载语音: '{keyword}' → {abs_path} ({ext})")

        if count > 0:
            logger.info(f"[VoiceDaka] 成功加载 {count} 个语音文件")
            logger.info(f"[VoiceDaka] 支持关键词: {', '.join(sorted(self.voice_map.keys()))}")
        else:
            logger.warning("[VoiceDaka] voices 目录无有效音频文件")

    async def on_message(self, event: AstrMessageEvent):
        if event.message_str is None:
            return False

        text = event.message_str.strip()
        logger.debug(f"[VoiceDaka] 收到消息: '{text}' (raw: '{event.message_str}')")

        if not text:
            logger.debug("[VoiceDaka] 空消息，跳过")
            return False

        matched_path: Optional[str] = None

        # 方式A: 完全匹配（严格）
        matched_path = self.voice_map.get(text)

        # 方式B: 包含关键词（更宽松，临时启用看是否触发）
        if matched_path is None:
            for kw, path in self.voice_map.items():
                if kw in text:
                    matched_path = path
                    logger.debug(f"[VoiceDaka] 包含匹配: '{kw}' in '{text}'")
                    break

        if matched_path is None:
            logger.debug(f"[VoiceDaka] 无匹配: '{text}'")
            return False

        try:
            logger.info(f"[VoiceDaka] 尝试发送: '{text}' → {matched_path}")
            chain = MessageChain()
            chain.append(Record(file=matched_path))
            await event.reply(chain)
            logger.info(f"[VoiceDaka] 发送成功: {matched_path}")
            return True
        except Exception as e:
            logger.error(f"[VoiceDaka] 发送失败: {str(e)}", exc_info=True)
            await event.reply(f"[调试] 语音发送出错: {str(e)}")
            return True
