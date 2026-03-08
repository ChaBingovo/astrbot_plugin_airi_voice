from pathlib import Path
from typing import Dict, Optional

# 关键：必须导入 filter 并用它装饰
from astrbot.api.star import Context, Star
from astrbot.api.event import AstrMessageEvent, MessageChain, filter  # ← 这里导入 filter
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
            logger.info("[VoiceDaka] 已创建 voices 目录")
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
            logger.info(f"[VoiceDaka] 加载完成：{count} 个语音可用")
            logger.info(f"[VoiceDaka] 关键词列表: {', '.join(self.voice_map.keys())}")
        else:
            logger.warning("[VoiceDaka] 无有效音频")

    # 核心修复：用 @filter.on_message() 注册，让插件收到所有消息
    @filter.on_message()  # 或 @filter.event_message_type("ALL") 如果上面不行，试这个
    async def on_message(self, event: AstrMessageEvent):
        if event.message_str is None:
            logger.debug("[VoiceDaka] 无文本内容，跳过")
            return False

        text = event.message_str.strip()
        logger.debug(f"[VoiceDaka] 收到文本消息: '{text}' (原始: '{event.message_str}')")

        if not text:
            return False

        matched_path: Optional[str] = self.voice_map.get(text)

        # 如果严格匹配失败，尝试包含匹配（更友好）
        if matched_path is None:
            for kw, path in self.voice_map.items():
                if kw in text:
                    matched_path = path
                    logger.debug(f"[VoiceDaka] 包含匹配成功: '{kw}' 在 '{text}' 中")
                    break

        if matched_path is None:
            logger.debug(f"[VoiceDaka] 未匹配到任何关键词: '{text}'")
            return False

        try:
            logger.info(f"[VoiceDaka] 准备发送语音: '{text}' → {matched_path}")
            chain = MessageChain()
            chain.append(Record(file=matched_path))
            await event.reply(chain)
            logger.info(f"[VoiceDaka] 语音发送成功")
            return True  # 拦截，不让其他插件再处理

        except Exception as e:
            logger.error(f"[VoiceDaka] 发送失败: {str(e)}", exc_info=True)
            await event.reply(f"语音出问题了: {str(e)}（可能是格式不支持，建议转成 .wav）")
            return True
