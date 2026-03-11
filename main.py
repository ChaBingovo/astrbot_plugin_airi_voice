from astrbot.api.all import *
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api import logger
from astrbot.core.star.star_tools import StarTools
from pathlib import Path
from typing import Dict
import re

ALLOWED_EXT = {'.mp3', '.wav', '.ogg', '.silk', '.amr'}

@register("airi_voice", "lidure", "输入关键词发送对应语音（本地 + 网页上传 + 引用保存）", "1.5", "https://github.com/Lidure/astrbot_plugin_airi_voice")
class AiriVoice(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)

        self.plugin_dir = Path(__file__).parent
        self.voice_dir = self.plugin_dir / "voices"

        self.data_dir = Path(StarTools.get_data_dir("astrbot_plugin_airi_voice"))
        self.extra_voice_dir = self.data_dir / "extra_voices"
        self.extra_voice_dir.mkdir(parents=True, exist_ok=True)

        self.voice_map: Dict[str, str] = {}
        self.sorted_keys: list[str] = []

        self._load_local_voices()

        self.config = config
        self.trigger_mode = (config or {}).get("trigger_mode", "direct")
        if self.trigger_mode not in {"prefix", "direct"}:
            logger.warning(f"[AiriVoice] 无效 trigger_mode '{self.trigger_mode}'，强制使用 direct")
            self.trigger_mode = "direct"
        logger.info(f"[AiriVoice] 当前触发模式：{self.trigger_mode}")

        self._load_web_voices(config)
        self.last_pool_len = len(config.get("extra_voice_pool", [])) if config else 0

        logger.info(f"[AiriVoice] 初始化完成，当前语音总数：{len(self.voice_map)} 个")

    def _load_local_voices(self):
        if not self.voice_dir.exists():
            self.voice_dir.mkdir(parents=True, exist_ok=True)
            logger.info("[AiriVoice] 已创建本地 voices 目录")

        count = 0
        for file_path in self.voice_dir.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in ALLOWED_EXT:
                keyword = file_path.stem.strip()
                if keyword in self.voice_map:
                    logger.warning(f"[AiriVoice] 本地关键词冲突：'{keyword}' 已存在，将被覆盖")
                self.voice_map[keyword] = str(file_path)
                count += 1
                logger.debug(f"[AiriVoice] 本地加载：'{keyword}' → {file_path}")

        if count > 0:
            logger.info(f"[AiriVoice] 从本地 voices 加载 {count} 个语音")

        self.sorted_keys = sorted(self.voice_map.keys())

    def _load_web_voices(self, config: dict = None):
        if config is None:
            logger.info("[AiriVoice] 未收到 config，不加载网页语音")
            return

        extra_pool = config.get("extra_voice_pool", [])
        if not extra_pool:
            logger.info("[AiriVoice] 无 extra_voice_pool 配置")
            return

        logger.info(f"[AiriVoice] 网页相对路径池：{extra_pool}")

        loaded = 0
        data_dir_resolved = self.data_dir.resolve()
        for rel_path in extra_pool:
            if not isinstance(rel_path, str) or not rel_path.strip():
                continue

            try:
                abs_path = (self.data_dir / rel_path).resolve()
                if not abs_path.is_relative_to(data_dir_resolved):
                    logger.warning(f"[AiriVoice] 检测到非法路径尝试: {rel_path} → {abs_path}")
                    continue
            except Exception as e:
                logger.warning(f"[AiriVoice] 路径解析失败: {rel_path} - {e}")
                continue

            if abs_path.exists() and abs_path.is_file():
                if abs_path.suffix.lower() not in ALLOWED_EXT:
                    logger.warning(f"[AiriVoice] 忽略非音频文件：{abs_path}")
                    continue
                keyword = abs_path.stem.strip()
                if keyword in self.voice_map:
                    logger.warning(f"[AiriVoice] 网页关键词冲突：'{keyword}' 已存在，将覆盖")
                self.voice_map[keyword] = str(abs_path)
                loaded += 1
                logger.info(f"[AiriVoice] 网页加载成功：'{keyword}' → {abs_path}")
            else:
                logger.warning(f"[AiriVoice] 网页文件不存在：{abs_path} (相对: {rel_path})")

        if loaded > 0:
            logger.info(f"[AiriVoice] 从网页配置加载 {loaded} 个额外语音")

        self.sorted_keys = sorted(self.voice_map.keys())

    @filter.regex(r"^\s*.+\s*$")
    async def voice_handler(self, event: AstrMessageEvent):
        text = (event.message_str or "").strip()
        if not text:
            return

        # 自动检测配置变化（网页上传后自动刷新）
        current_pool_len = len(self.config.get("extra_voice_pool", [])) if self.config else 0
        if current_pool_len > self.last_pool_len:
            logger.info("[AiriVoice] 检测到网页配置变化，自动刷新语音列表")
            self._load_web_voices(self.config)
            self.last_pool_len = current_pool_len

        keyword = text

        if self.trigger_mode == "prefix":
            match = re.search(r"^#voice\s+(.+)", text, re.I)
            if not match:
                return
            keyword = match.group(1).strip()

        matched_path = self.voice_map.get(keyword)
        if matched_path is None:
            return

        try:
            logger.info(f"[AiriVoice] 触发语音（模式: {self.trigger_mode}）：'{keyword}' → {matched_path}")
            chain = [Record.fromFileSystem(matched_path)]
            yield event.chain_result(chain)
        except Exception as e:
            logger.error(f"[AiriVoice] 发送失败 '{keyword}': {str(e)}", exc_info=True)
            yield event.plain_result(f"语音发送失败：{str(e)}")

    @filter.command("voice.add")
    async def add_voice(self, event: AstrMessageEvent):
        """引用一条语音消息 + voice.add 名字 → 保存为 silk 文件"""
        if not event.quote_message:
            yield event.plain_result("请引用一条语音消息后再使用 voice.add 名字")
            return

        args = (event.message_str or "").strip().split(maxsplit=1)
        if len(args) < 2:
            yield event.plain_result("用法：voice.add 名字\n请引用一条语音消息")
            return

        name = args[1].strip()
        if not name:
            yield event.plain_result("名字不能为空")
            return

        # 从引用消息中找 Record（语音）segment
        voice_segment = None
        for seg in event.quote_message.chain:
            if isinstance(seg, Record):
                voice_segment = seg
                break

        if not voice_segment:
            yield event.plain_result("引用的消息中没有语音哦～请引用一条语音消息")
            return

        # 优先尝试获取 silk 数据（QQ 语音通常是 silk 格式）
        voice_data = None
        if hasattr(voice_segment, 'data') and voice_segment.data:
            voice_data = voice_segment.data
        elif hasattr(voice_segment, 'file') and voice_segment.file:
            # 如果是 file 路径，读取内容
            try:
                with open(voice_segment.file, 'rb') as f:
                    voice_data = f.read()
            except Exception as e:
                logger.error(f"读取引用语音文件失败: {e}")
                yield event.plain_result("无法读取引用的语音文件")
                return
        else:
            yield event.plain_result("无法获取语音数据（不支持的语音格式）")
            return

        if not voice_data:
            yield event.plain_result("语音数据为空，无法保存")
            return

        # 保存为 silk 文件（即使原格式不是 silk，也强制保存为 .silk 后缀）
        save_name = f"{name}.silk"
        save_path = self.voice_dir / save_name

        try:
            with open(save_path, 'wb') as f:
                f.write(voice_data)
            logger.info(f"[AiriVoice] 成功保存语音：{save_name} → {save_path}")

            # 加入 voice_map
            keyword = name.strip()
            if keyword in self.voice_map:
                logger.warning(f"[AiriVoice] 关键词冲突：'{keyword}' 已存在，将覆盖")
            self.voice_map[keyword] = str(save_path)
            self.sorted_keys = sorted(self.voice_map.keys())

            yield event.plain_result(f"已保存语音为 '{keyword}'！\n后续直接输入 {keyword} 即可触发发送～")
        except Exception as e:
            logger.error(f"[AiriVoice] 保存语音失败: {e}", exc_info=True)
            yield event.plain_result(f"保存失败：{str(e)}")

    @filter.command("voice.list")
    async def list_voices(self, event: AstrMessageEvent):
        if not self.sorted_keys:
            yield event.plain_result("当前没有可用语音～快去 voices/ 或网页配置添加吧！")
            return

        args = (event.message_str or "").strip().split()
        page = 1
        if len(args) > 1 and args[1].isdigit():
            page = int(args[1])
            if page < 1:
                page = 1

        total = len(self.sorted_keys)
        page_size = 25
        total_pages = (total + page_size - 1) // page_size

        if page > total_pages:
            yield event.plain_result(f"页码过大～总共只有 {total_pages} 页（共 {total} 个关键词）")
            return

        start = (page - 1) * page_size
        end = start + page_size
        page_keys = self.sorted_keys[start:end]

        msg = f"可用语音关键词（第 {page}/{total_pages} 页，共 {total} 个）：\n"
        for k in page_keys:
            msg += f"・ {k}\n"

        nav = ""
        if total_pages > 1:
            if page > 1:
                nav += f" /voice.list {page-1} ← 上一页"
            if page < total_pages:
                nav += f" /voice.list {page+1} → 下一页"
            if nav:
                msg += f"\n{nav.strip()}"

        yield event.plain_result(msg)
