from pathlib import Path
from typing import Dict, Optional

from astrbot.api.star import Context, Star
from astrbot.api.event import AstrMessageEvent, MessageChain, filter  # 只导入这些
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
            logger.info("[VoiceDaka] voices 目录已创建")
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
                    logger.debug(f"[VoiceDaka] 加载语音: '{keyword}' → {abs_path}")

        if count > 0:
            logger.info(f"[VoiceDaka] 加载完成：{count} 个语音")
            logger.info(f"[VoiceDaka] 关键词: {', '.join(self.voice_map.keys())}")
        else:
            logger.warning("[VoiceDaka] 无音频文件")

    # 为每个关键词注册一个 command（用户发纯文本 "打卡啦摩托" 也能触发）
    # 如果关键词很多，可以动态生成，但先硬编码测试
    @filter.command("打卡啦摩托")
    async def handle_daka(self, event: AstrMessageEvent):
        await self._send_matched_voice(event, "打卡啦摩托")

    # 如果有第二个关键词，比如 "测试语音"，加一条：
    # @filter.command("测试语音")
    # async def handle_test(self, event: AstrMessageEvent):
    #     await self._send_matched_voice(event, "测试语音")

    # 通用发送函数（避免重复代码）
    async def _send_matched_voice(self, event: AstrMessageEvent, keyword: str):
        matched_path = self.voice_map.get(keyword)
        if not matched_path:
            logger.warning(f"[VoiceDaka] 关键词 '{keyword}' 无对应文件")
            return

        try:
            logger.info(f"[VoiceDaka] 发送: '{keyword}' → {matched_path}")
            chain = MessageChain()
            chain.append(Record(file=matched_path))
            await event.reply(chain)
            return  # 成功发送

        except Exception as e:
            logger.error(f"[VoiceDaka] 发送失败 '{keyword}': {str(e)}", exc_info=True)
            await event.reply(f"语音出错了（建议用 .wav 格式）：{str(e)}")

    # 如果想支持“消息包含关键词”而不是严格命令匹配，可加这个（如果框架调用 on_message）
    async def on_message(self, event: AstrMessageEvent):  # 作为 fallback
        text = (event.message_str or "").strip()
        if not text:
            return

        for kw in self.voice_map:
            if kw in text:  # 包含匹配，更宽松
                await self._send_matched_voice(event, kw)
                return  # 处理一个就够
