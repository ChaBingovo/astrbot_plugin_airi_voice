import os
import json
import aiohttp
from pathlib import Path
from astrbot.api import star, on_message, AstrBotMessage, MessageChain
from astrbot.api.event import filter
from astrbot.api.star import Context, Star
from astrbot.core.config.default import VERSION

@star(
    name="astrbot_plugin_airi_voice",
    version="2.4.0",
    author="lidure",
    description="输入关键词即可触发可爱语音，支持引用添加、网页上传和权限控制。"
)
class AiriVoicePlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.config = context.get_config()
        # 获取数据目录 (用于持久化存储用户上传的语音)
        self.data_dir = context.get_data_dir()
        self.extra_voice_dir = self.data_dir / "extra_voices"
        
        # 确保目录存在
        if not self.extra_voice_dir.exists():
            self.extra_voice_dir.mkdir(parents=True, exist_ok=True)
            
        # 初始化配置项 (如果 config.json 中没有这些字段)
        if "extra_voice_pool" not in self.config:
            self.config["extra_voice_pool"] = []
        if "trigger_mode" not in self.config:
            self.config["trigger_mode"] = "direct" # direct or prefix
        if "admin_mode" not in self.config:
            self.config["admin_mode"] = "whitelist" # all, admin, whitelist
        if "admin_whitelist" not in self.config:
            self.config["admin_whitelist"] = []
            
        # 保存一次配置以确保新字段写入 config.json
        self.save_config()
        
        # 构建完整语音列表 (本地 voices + 额外 extra_voices)
        self.voice_map = self._build_voice_map()

    def _build_voice_map(self) -> dict:
        """扫描所有可用语音文件，构建 {关键词: 文件路径} 映射"""
        voice_map = {}
        
        # 1. 扫描本地 voices 目录 (插件自带)
        local_voice_dir = Path(__file__).parent / "voices"
        if local_voice_dir.exists():
            for f in local_voice_dir.iterdir():
                if f.is_file() and f.suffix.lower() in ['.mp3', '.wav', '.ogg', '.silk', '.amr']:
                    key = f.stem
                    voice_map[key] = str(f)

        # 2. 扫描额外 voices 目录 (用户添加/网页上传)
        if self.extra_voice_dir.exists():
            for f in self.extra_voice_dir.iterdir():
                if f.is_file() and f.suffix.lower() in ['.mp3', '.wav', '.ogg', '.silk', '.amr']:
                    key = f.stem
                    # 检查是否在配置池中 (防止手动放入但未配置的文件被误触，或者作为白名单机制)
                    # 这里策略：只要在 extra_voices 目录且文件名匹配，就认为有效
                    # 或者严格模式：必须要在 config['extra_voice_pool'] 里
                    # 为了兼容性，我们采用：如果在 pool 里，或者 pool 为空则全部加载
                    pool = self.config.get("extra_voice_pool", [])
                    if not pool or key in pool:
                        voice_map[key] = str(f)
                        
        return voice_map

    def save_config(self):
        """保存配置到 config.json"""
        try:
            config_path = Path(__file__).parent / "config.json"
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=4)
            # 通知 AstrBot 配置已更新 (可选，视框架版本而定)
            # self.context.update_config(self.config) 
        except Exception as e:
            self.logger.error(f"保存配置失败: {e}")

    def _check_permission(self, event: AstrBotMessage) -> bool:
        """检查用户权限"""
        mode = self.config.get("admin_mode", "whitelist")
        if mode == "all":
            return True
        if mode == "admin":
            return event.get_sender_id() in self.context.get_admin_ids()
        
        # whitelist 模式
        uid = event.get_sender_id()
        nickname = event.get_sender_name()
        allow_list = self.config.get("admin_whitelist", [])
        return uid in allow_list or nickname in allow_list

    async def _download_file(self, url: str, save_path: Path) -> bool:
        """下载文件辅助函数"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        with open(save_path, 'wb') as f:
                            f.write(await resp.read())
                        return True
        except Exception as e:
            self.logger.error(f"下载文件失败: {e}")
        return False

    @on_message()
    async def on_message_handler(self, event: AstrBotMessage, message_chain: MessageChain):
        text = message_chain.text()
        if not text:
            return

        # 1. 处理命令
        if text.startswith("/"):
            parts = text.split()
            cmd = parts[0]
            args = parts[1:] if len(parts) > 1 else []

            # --- 命令: voice.add (核心修改点) ---
            if cmd == "/voice.add":
                if not self._check_permission(event):
                    await event.send("❌ 权限不足：只有管理员或白名单用户可添加语音。")
                    return
                
                if not event.get_message_ref():
                    await event.send("❌ 用法错误：请引用一条语音消息后，再发送 `/voice.add 关键词`")
                    return
                
                if not args:
                    await event.send("❌ 用法错误：请指定关键词，例如 `/voice.add 早上好`")
                    return

                voice_name = args[0]
                ref_msg = event.get_message_ref()
                
                # 查找引用消息中的语音/文件部分
                file_url = None
                file_ext = "mp3" # 默认
                
                for comp in ref_msg.message_chain:
                    if hasattr(comp, 'url') and hasattr(comp, 'type'):
                        # 适配不同平台的语音消息类型
                        if comp.type in ['voice', 'file', 'record']: 
                            file_url = comp.url
                            # 尝试从 url 或 filename 获取扩展名
                            if hasattr(comp, 'name') and comp.name:
                                file_ext = comp.name.split('.')[-1] if '.' in comp.name else 'mp3'
                            elif file_url and '.' in file_url:
                                file_ext = file_url.split('.')[-1].split('?')[0]
                            break
                
                if not file_url:
                    await event.send("❌ 未找到引用的语音文件，请确保引用的是语音消息。")
                    return

                # 构造保存路径
                safe_name = "".join([c for c in voice_name if c.isalnum() or c in "_-"])
                file_name = f"{safe_name}.{file_ext}"
                save_path = self.extra_voice_dir / file_name

                # 下载文件
                if await self._download_file(file_url, save_path):
                    # ✅ 核心逻辑：更新配置并保存
                    pool = self.config.get("extra_voice_pool", [])
                    if safe_name not in pool:
                        pool.append(safe_name)
                        self.config["extra_voice_pool"] = pool
                        self.save_config() # <--- 关键：持久化保存
                    
                    # 刷新内存中的映射
                    self.voice_map = self._build_voice_map()
                    
                    await event.send(f"✅ 语音 `{safe_name}` 添加成功！\n已自动保存到配置文件，重启后依然有效。")
                else:
                    await event.send("❌ 语音文件下载失败。")
                return

            # --- 命令: voice.delete ---
            if cmd == "/voice.delete":
                if not self._check_permission(event):
                    await event.send("❌ 权限不足。")
                    return
                if not args:
                    await event.send("❌ 用法：`/voice.delete 关键词`")
                    return
                
                name = args[0]
                # 只能在 extra_voices 中删除
                target_file = self.extra_voice_dir / f"{name}.mp3" # 简单处理，实际应遍历后缀
                found_file = None
                for f in self.extra_voice_dir.iterdir():
                    if f.stem == name:
                        found_file = f
                        break
                
                if found_file:
                    try:
                        found_file.unlink()
                        # 从配置池移除
                        pool = self.config.get("extra_voice_pool", [])
                        if name in pool:
                            pool.remove(name)
                            self.config["extra_voice_pool"] = pool
                            self.save_config()
                        self.voice_map = self._build_voice_map()
                        await event.send(f"🗑️ 语音 `{name}` 已删除。")
                    except Exception as e:
                        await event.send(f"❌ 删除失败: {e}")
                else:
                    await event.send(f"❌ 未找到名为 `{name}` 的用户自定义语音。")
                return

            # --- 命令: voice.reload ---
            if cmd == "/voice.reload":
                if not self._check_permission(event):
                    await event.send("❌ 权限不足。")
                    return
                self.voice_map = self._build_voice_map()
                await event.send("🔄 语音列表已重新加载。")
                return

            # --- 命令: voice.list ---
            if cmd == "/voice.list":
                page = 1
                if args and args[0].isdigit():
                    page = int(args[0])
                
                keys = sorted(self.voice_map.keys())
                per_page = 25
                total_pages = (len(keys) + per_page - 1) // per_page
                
                if page < 1: page = 1
                if page > total_pages: page = total_pages if total_pages > 0 else 1
                
                start_idx = (page - 1) * per_page
                end_idx = start_idx + per_page
                current_keys = keys[start_idx:end_idx]
                
                msg = f"📄 语音列表 (第 {page}/{total_pages} 页，共 {len(keys)} 条):\n"
                for k in current_keys:
                    msg += f"• {k}\n"
                
                if total_pages > 1:
                    msg += "\n💡 使用 `/voice.list 页码` 翻页"
                
                await event.send(msg)
                return

            # --- 命令: voice.help ---
            if cmd == "/voice.help":
                help_text = (
                    "🌸 **Airi Voice 帮助**\n\n"
                    "1. **触发**: 直接发送关键词 (如 `早上好`)\n"
                    "2. **添加**: 引用语音消息 + `/voice.add 关键词`\n"
                    "3. **列表**: `/voice.list`\n"
                    "4. **模式**: 当前为 `" + self.config.get("trigger_mode", "direct") + "` 模式\n"
                    "   - `direct`: 直接发关键词\n"
                    "   - `prefix`: 需发送 `#voice 关键词`"
                )
                await event.send(help_text)
                return
            
            # --- 命令: voice.check ---
            if cmd == "/voice.check":
                is_admin = self._check_permission(event)
                status = "✅ 有权限" if is_admin else "❌ 无权限"
                await event.send(f"当前用户权限状态: {status}\n模式: {self.config.get('admin_mode')}")
                return

        # 2. 处理语音触发
        trigger_mode = self.config.get("trigger_mode", "direct")
        keyword = text.strip()

        # 前缀模式处理
        if trigger_mode == "prefix":
            if keyword.startswith("#voice "):
                keyword = keyword[7:].strip()
            else:
                return # 非前缀开头，不处理
        
        # 匹配语音
        if keyword in self.voice_map:
            file_path = self.voice_map[keyword]
            if os.path.exists(file_path):
                # 发送语音 (AstrBot 通用方法)
                # 注意：不同平台可能需要不同的发送方式，这里使用通用的 file 发送
                await event.send_file(file_path)
            else:
                self.logger.warning(f"语音文件不存在: {file_path}")
