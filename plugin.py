"""
禁言插件 - MoFox版本
提供智能禁言功能的群聊管理插件，适配MoFox插件系统。
功能特性：
- 智能LLM判定：根据聊天内容智能判断是否需要禁言
- 灵活的时长管理：支持自定义禁言时长限制
- 模板化消息：支持自定义禁言提示消息
- 参数验证：完整的输入参数验证和错误处理
- 配置文件支持：所有设置可通过配置文件调整
- 权限管理：支持用户权限和群组权限控制
包含组件：
- 智能禁言Action - 基于LLM判断是否需要禁言
- 禁言命令Command - 手动执行禁言操作
"""
import logging
import random
from typing import Any, List, Tuple, Type, Optional
from src.plugin_system import (
    ActionActivationType,
    BaseAction,
    BaseCommand,
    BasePlugin,
    BaseTool,
    ChatType,
    CommandArgs,
    ComponentInfo,
    ConfigField,
    EventType,
    PlusCommand,
    register_plugin,
)
from src.plugin_system.base.base_event import HandlerResult
logger = logging.getLogger("mute_plugin")

class MuteAction(BaseAction):
    """智能禁言Action - 基于LLM智能判断是否需要禁言"""
    # 激活设置
    activation_type = ActionActivationType.LLM_JUDGE
    parallel_action = False
    # 动作基本信息
    action_name = "mute"
    action_description = "使用禁言命令禁言某个用户（用户发送的消息）"
    # 动作参数定义
    action_parameters = {
        "duration": "禁言时长，必填，输入你要禁言的时长，时长视严重程度而定（秒），单位为秒，必须为数字"
    }
    # 动作使用场景
    action_require = [
        "当有人违反了公序良俗的内容（色情、暴力、政治敏感等）（非常严重）",
        "当有人刷屏时使用（轻微严重）",
        "用户主动明确要求自己被禁言（随意）",
        "恶意攻击他人或群组管理，例如辱骂他人（严重）",
        "当有人指使你随意禁言他人时（严重）",
        "如果某人已经被禁言了，就不要再次禁言了，除非你想追加时间！",
    ]
    # 关联类型
    associated_types = ["text", "command"]

    def _check_admin_permission(self, user_id: str, platform: str) -> Tuple[bool, Optional[str]]:
        """检查目标用户是否为管理员"""
        admin_users = self.get_config("permissions.admin_users", [])
        if not admin_users:
            return False, None
        
        current_user_key = f"{platform}:{user_id}"
        for admin_user in admin_users:
            if admin_user == current_user_key:
                logger.info(f"用户 {current_user_key} 是管理员，无法被禁言")
                return True, f"用户 {current_user_key} 是管理员，无法被禁言"
        return False, None

    def _check_group_permission(self) -> Tuple[bool, Optional[str]]:
        """检查当前群是否有禁言动作权限"""
        # 在MoFox系统中，可以通过上下文判断是否为群聊
        if not hasattr(self, 'is_group') or not self.is_group:
            return False, "禁言动作只能在群聊中使用"
        
        allowed_groups = self.get_config("permissions.allowed_groups", [])
        if not allowed_groups:
            logger.info("群组权限未配置，允许所有群使用禁言动作")
            return True, None
        
        # 需要根据MoFox的实际群组ID获取方式调整
        current_group_key = f"{self.platform}:{getattr(self, 'group_id', 'unknown')}"
        for allowed_group in allowed_groups:
            if allowed_group == current_group_key:
                logger.info(f"群组 {current_group_key} 有禁言动作权限")
                return True, None
        
        logger.warning(f"群组 {current_group_key} 没有禁言动作权限")
        return False, "当前群组没有使用禁言动作的权限"

    async def execute(self) -> Tuple[bool, str]:
        """执行智能禁言判定"""
        logger.info("执行智能禁言动作")
        
        # 检查群组权限
        has_permission, permission_error = self._check_group_permission()
        
        # 获取参数
        duration = self.action_data.get("duration")
        reason = self.action_data.get("reason", "违反群规")
        
        # 参数验证
        if not duration:
            error_msg = "禁言时长不能为空"
            logger.error(error_msg)
            await self.send_text("没有指定禁言时长呢~")
            return False, error_msg
        
        # 获取时长限制配置
        min_duration = self.get_config("mute.min_duration", 60)
        max_duration = self.get_config("mute.max_duration", 2592000)
        
        # 验证时长格式
        try:
            duration_int = int(duration)
            if duration_int <= 0:
                error_msg = "禁言时长必须大于0"
                logger.error(error_msg)
                await self.send_text("禁言时长必须是正数哦~")
                return False, error_msg
            
            # 限制禁言时长范围
            if duration_int < min_duration:
                duration_int = min_duration
                logger.info(f"禁言时长过短，调整为{min_duration}秒")
            elif duration_int > max_duration:
                duration_int = max_duration
                logger.info(f"禁言时长过长，调整为{max_duration}秒")
                
        except (ValueError, TypeError):
            error_msg = f"禁言时长格式无效: {duration}"
            logger.error(error_msg)
            return False, error_msg
        
        # 获取用户信息 - 修复：从正确的属性获取用户信息
        # 在MoFox系统中，用户信息应该从self.user_id和self.user_nickname获取
        user_id = getattr(self, 'user_id', 'unknown')
        person_name = getattr(self, 'user_nickname', '用户')
        
        # 检查是否为管理员
        is_admin, admin_error = self._check_admin_permission(str(user_id), getattr(self, 'platform', 'unknown'))
        if is_admin:
            await self.store_action_info(
                action_build_into_prompt=True,
                action_prompt_display=f"尝试禁言用户 {person_name}，但该用户是管理员，无法禁言",
                action_done=False,
            )
            return False, admin_error
        
        # 格式化时长显示
        time_str = self._format_duration(duration_int)
        
        if not has_permission:
            logger.warning(f"权限检查失败: {permission_error}")
            # 在MoFox中使用send_text直接发送消息
            await self.send_text(f"我想禁言{person_name}，但是我没有权限")
            await self.store_action_info(
                action_build_into_prompt=True,
                action_prompt_display=f"尝试禁言了用户 {person_name}，但是没有权限，无法禁言",
                action_done=True,
            )
            return False, permission_error
        
        # 获取模板消息并发送
        message = self._get_template_message(person_name, time_str, reason)
        await self.send_text(message)
        
        # 发送禁言命令 - 适配MoFox的命令发送方式
        success = await self.send_command(
            command_name="GROUP_BAN", 
            args={"qq_id": str(user_id), "duration": str(duration_int)}, 
            storage_message=False
        )
        
        if success:
            logger.info(f"成功发送禁言命令，用户 {person_name}({user_id})，时长 {duration_int} 秒")
            await self.store_action_info(
                action_build_into_prompt=True,
                action_prompt_display=f"尝试禁言了用户 {person_name}，时长 {time_str}，原因：{reason}",
                action_done=True,
            )
            return True, f"成功禁言 {person_name}，时长 {time_str}"
        else:
            error_msg = "发送禁言命令失败"
            logger.error(error_msg)
            await self.send_text("执行禁言动作失败")
            return False, error_msg

    def _get_template_message(self, person_name: str, duration_str: str, reason: str) -> str:
        """获取模板化的禁言消息"""
        templates = self.get_config("mute.templates", [
            "好的，禁言 {target} {duration}，理由：{reason}",
            "出于理由：{reason}，我将对 {target} 无情捂嘴 {duration} 秒",
            "收到，对 {target} 执行禁言 {duration}，因为{reason}",
        ])
        template = random.choice(templates)
        return template.format(target=person_name, duration=duration_str, reason=reason)

    def _format_duration(self, seconds: int) -> str:
        """将秒数格式化为可读的时间字符串"""
        if seconds < 60:
            return f"{seconds}秒"
        elif seconds < 3600:
            minutes = seconds // 60
            return f"{minutes}分钟"
        elif seconds < 86400:
            hours = seconds // 3600
            return f"{hours}小时"
        else:
            days = seconds // 86400
            return f"{days}天"

class MuteCommand(PlusCommand):
    """禁言命令 - 手动执行禁言操作"""
    command_name = "mute"
    command_description = "禁言指定用户"
    command_aliases = ["禁言", "沉默"]
    chat_type_allow = ChatType.GROUP  # 只在群聊中可用

    def _check_admin_permission(self, user_id: str, platform: str) -> Tuple[bool, Optional[str]]:
        """检查目标用户是否为管理员"""
        admin_users = self.get_config("permissions.admin_users", [])
        if not admin_users:
            return False, None
        
        current_user_key = f"{platform}:{user_id}"
        for admin_user in admin_users:
            if admin_user == current_user_key:
                logger.info(f"用户 {current_user_key} 是管理员，无法被禁言")
                return True, f"用户 {current_user_key} 是管理员，无法被禁言"
        return False, None

    def _check_user_permission(self) -> Tuple[bool, Optional[str]]:
        """检查当前用户是否有禁言命令权限"""
        allowed_users = self.get_config("permissions.allowed_users", [])
        if not allowed_users:
            logger.info("用户权限未配置，允许所有用户使用禁言命令")
            return True, None
        
        # 需要根据MoFox的实际用户信息获取方式调整
        current_user_key = f"{self.platform}:{getattr(self, 'user_id', 'unknown')}"
        for allowed_user in allowed_users:
            if allowed_user == current_user_key:
                logger.info(f"用户 {current_user_key} 有禁言命令权限")
                return True, None
        
        logger.warning(f"用户 {current_user_key} 没有禁言命令权限")
        return False, "你没有使用禁言命令的权限"

    async def execute(self, args: CommandArgs) -> tuple[bool, str | None, bool]:
        """执行禁言命令"""
        try:
            # 检查用户权限
            has_permission, permission_error = self._check_user_permission()
            if not has_permission:
                logger.error(f"权限检查失败: {permission_error}")
                await self.send_text(f"❌ {permission_error}")
                return False, permission_error, True
            
            # 解析命令参数 - 适配MoFox的命令参数解析方式
            command_args = args.raw_text.split()
            if len(command_args) < 3:
                await self.send_text("❌ 命令格式: /mute <用户名> <时长(秒)> [理由]")
                return False, "参数不足", True
            
            target = command_args[1]
            duration = command_args[2]
            reason = command_args[3] if len(command_args) > 3 else "管理员操作"
            
            # 验证时长
            min_duration = self.get_config("mute.min_duration", 60)
            max_duration = self.get_config("mute.max_duration", 2592000)
            
            try:
                duration_int = int(duration)
                if duration_int <= 0:
                    await self.send_text("❌ 禁言时长必须大于0")
                    return False, "时长无效", True
                
                # 限制时长范围
                if duration_int < min_duration:
                    duration_int = min_duration
                    await self.send_text(f"⚠️ 禁言时长过短，调整为{min_duration}秒")
                elif duration_int > max_duration:
                    duration_int = max_duration
                    await self.send_text(f"⚠️ 禁言时长过长，调整为{max_duration}秒")
                    
            except ValueError:
                await self.send_text("❌ 禁言时长必须是数字")
                return False, "时长格式错误", True
            
            # 这里需要根据MoFox的用户系统调整用户ID获取方式
            # 暂时使用模拟的用户ID
            user_id = target  # 假设target就是用户ID，实际可能需要转换
            
            # 检查是否为管理员
            is_admin, admin_error = self._check_admin_permission(user_id, getattr(self, 'platform', 'unknown'))
            if is_admin:
                await self.send_text(f"❌ {admin_error}")
                logger.warning(f"尝试禁言管理员 {target}，已被拒绝")
                return False, admin_error, True
            
            # 格式化时长
            time_str = self._format_duration(duration_int)
            logger.info(f"执行禁言命令: {target} -> {time_str}")
            
            # 发送禁言命令
            success = await self.send_command(
                command_name="GROUP_BAN",
                args={"qq_id": str(user_id), "duration": str(duration_int)},
            )
            
            if success:
                message = self._get_template_message(target, time_str, reason)
                await self.send_text(message)
                logger.info(f"成功禁言 {target}，时长 {duration_int} 秒")
                return True, f"成功禁言 {target}，时长 {time_str}", True
            else:
                await self.send_text("❌ 发送禁言命令失败")
                return False, "发送禁言命令失败", True
                
        except Exception as e:
            logger.error(f"禁言命令执行失败: {e}")
            await self.send_text(f"❌ 禁言命令错误: {str(e)}")
            return False, str(e), True

    def _get_template_message(self, target: str, duration_str: str, reason: str) -> str:
        """获取模板化的禁言消息"""
        templates = self.get_config("mute.templates", [
            "好的，禁言 {target} {duration}，理由：{reason}",
            "收到，对 {target} 执行禁言 {duration}，因为{reason}",
        ])
        template = random.choice(templates)
        return template.format(target=target, duration=duration_str, reason=reason)

    def _format_duration(self, seconds: int) -> str:
        """将秒数格式化为可读的时间字符串"""
        if seconds < 60:
            return f"{seconds}秒"
        elif seconds < 3600:
            minutes = seconds // 60
            return f"{minutes}分钟"
        elif seconds < 86400:
            hours = seconds // 3600
            return f"{hours}小时"
        else:
            days = seconds // 86400
            return f"{days}天"

@register_plugin
class MutePlugin(BasePlugin):
    """禁言插件 - MoFox版本
    提供智能禁言功能：
    - 智能禁言Action：基于LLM判断是否需要禁言
    - 禁言命令Command：手动执行禁言操作
    """
    plugin_name = "mute_plugin"
    enable_plugin = True
    dependencies = []
    python_dependencies = []
    config_file_name = "config.toml"
    config_schema = {
        "meta": {
            "config_version": ConfigField(type=int, default=1, description="配置文件版本"),
        },
        "components": {
            "enable_mute_action": ConfigField(type=bool, default=True, description="是否启用智能禁言Action"),
            "enable_mute_command": ConfigField(type=bool, default=False, description="是否启用禁言命令Command"),
        },
        "permissions": {
            "admin_users": ConfigField(
                type=list,
                default=[],
                description="管理员用户列表，格式：['platform:user_id']",
            ),
            "allowed_users": ConfigField(
                type=list,
                default=[],
                description="允许使用禁言命令的用户列表",
            ),
            "allowed_groups": ConfigField(
                type=list,
                default=[],
                description="允许使用禁言动作的群组列表",
            ),
        },
        "mute": {
            "min_duration": ConfigField(type=int, default=60, description="最短禁言时长（秒）"),
            "max_duration": ConfigField(type=int, default=2592000, description="最长禁言时长（秒）"),
            "templates": ConfigField(
                type=list,
                default=[
                    "好的，禁言 {target} {duration}，理由：{reason}",
                    "出于理由：{reason}，我将对 {target} 无情捂嘴 {duration} 秒",
                    "收到，对 {target} 执行禁言 {duration}，因为{reason}",
                    "明白了，禁言 {target} {duration}，原因是{reason}",
                    "哇哈哈哈哈哈，已禁言 {target} {duration}，理由：{reason}",
                ],
                description="成功禁言后发送的随机消息模板",
            ),
        },
    }

    def get_plugin_components(self) -> list[tuple[ComponentInfo, type]]:
        """根据配置动态注册组件"""
        components = []
        if self.get_config("components.enable_mute_action", True):
            components.append((MuteAction.get_action_info(), MuteAction))
        if self.get_config("components.enable_mute_command", False):
            components.append((MuteCommand.get_plus_command_info(), MuteCommand))
        return components