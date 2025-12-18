import re
from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, Any, List
from datetime import datetime

# ==========================================
# 1. 基础架构定义
# ==========================================


class ActionType(Enum):
    """规则评估结果类型"""
    PASS = "pass"       # 自动放行
    BLOCK = "block"     # 自动拦截
    REVIEW = "review"   # 转人工审批


class RuleResult:
    """规则返回结果"""

    def __init__(self, action: ActionType, reason: str = ""):
        self.action = action
        self.reason = reason

    def to_dict(self) -> Dict[str, str]:
        return {"action": self.action.value, "reason": self.reason}


class BaseRule(ABC):
    """规则基类 (策略模式接口)"""
    @abstractmethod
    def evaluate(self, state: Dict[str, Any]) -> RuleResult:
        pass


# ==========================================
# 2. 旅行场景专用安全规则
# ==========================================


class PIISafetyRule(BaseRule):
    """
    【规则1: 隐私泄露防护】
    检测对话中是否包含明文的身份证号、信用卡号或护照信息。
    """

    def evaluate(self, state: Dict[str, Any]) -> RuleResult:
        messages = state.get("messages", [])
        if not messages:
            return RuleResult(ActionType.PASS)

        last_msg = messages[-1]
        last_content = last_msg if isinstance(
            last_msg, str) else getattr(last_msg, 'content', '')

        # 敏感信息正则模式
        patterns = {
            "信用卡号": r"\b(?:\d[ -]*?){13,16}\b",
            "身份证号": r"\b\d{17}[\dXx]\b",
            "护照号": r"\b[A-Z]{1,2}\d{7,9}\b"
        }

        for p_name, pattern in patterns.items():
            if re.search(pattern, last_content):
                return RuleResult(ActionType.BLOCK, f"检测到明文敏感信息 ({p_name})，禁止传输")

        return RuleResult(ActionType.PASS)


class PromptInjectionRule(BaseRule):
    """
    【规则2: 提示词注入防御】
    防止用户试图修改 Agent 的系统设定 (例如要求退款、修改价格)。
    """

    def evaluate(self, state: Dict[str, Any]) -> RuleResult:
        messages = state.get("messages", [])
        if not messages:
            return RuleResult(ActionType.PASS)

        last_msg = messages[-1]
        last_content = last_msg if isinstance(
            last_msg, str) else getattr(last_msg, 'content', '')
        content_lower = last_content.lower()

        # 危险意图关键词
        risk_keywords = [
            "ignore previous instructions",
            "忽略之前的指令",
            "system override",
            "refund immediately",
            "立即退款",
            "change price to",
            "修改价格",
            "免费预订",
            "绕过验证"
        ]

        for word in risk_keywords:
            if word in content_lower:
                return RuleResult(ActionType.BLOCK, f"检测到潜在的 Prompt 注入攻击: {word}")

        return RuleResult(ActionType.PASS)


class FinancialTransactionRule(BaseRule):
    """
    【规则3: 金融风控】
    拦截所有涉及支付的步骤 (pay_flight, pay_hotel)。
    除非已经获得明确的 human_approval 标记。
    """

    def evaluate(self, state: Dict[str, Any]) -> RuleResult:
        current_step = state.get("step")

        # 关键支付步骤列表
        payment_steps = ["pay_flight", "pay_hotel"]

        if current_step in payment_steps:
            # 检查状态中是否已有授权标记
            if state.get("human_approval") is True:
                return RuleResult(ActionType.PASS, "已获得人工授权")
            else:
                return RuleResult(ActionType.REVIEW, f"执行支付步骤 ({current_step}) 前必须进行人工核验")

        return RuleResult(ActionType.PASS)


class NightCurfewRule(BaseRule):
    """
    【规则4: 夜间风控】
    23:00 - 06:00 禁止预订类操作
    """

    def evaluate(self, state: Dict[str, Any]) -> RuleResult:
        current_step = state.get("step", "")

        # 只针对预订/支付类步骤
        booking_steps = ["pay_flight", "pay_hotel",
                         "select_flight", "select_hotel"]
        if current_step not in booking_steps:
            return RuleResult(ActionType.PASS)

        current_hour = datetime.now().hour
        if current_hour >= 23 or current_hour < 6:
            return RuleResult(ActionType.BLOCK, "系统维护时间 (23:00-06:00) 禁止下单")

        return RuleResult(ActionType.PASS)


class SensitiveLocationRule(BaseRule):
    """
    【规则5: 敏感地点拦截】
    拦截前往高风险地区的预订
    """

    # 高风险地区列表 (示例)
    HIGH_RISK_LOCATIONS = ["朝鲜", "叙利亚", "DPRK", "Syria"]

    def evaluate(self, state: Dict[str, Any]) -> RuleResult:
        destination = state.get("destination", "")

        for loc in self.HIGH_RISK_LOCATIONS:
            if loc.lower() in destination.lower():
                return RuleResult(ActionType.BLOCK, f"目的地 ({destination}) 处于高风险地区，禁止预订")

        return RuleResult(ActionType.PASS)


# ==========================================
# 3. 规则引擎 (Rule Engine)
# ==========================================


class RuleEngine:
    """规则引擎：管理并执行所有规则"""

    def __init__(self, rules: List[BaseRule] = None):
        # 按优先级注册规则 (越靠前优先级越高)
        self.rules = rules or [
            PIISafetyRule(),           # 优先级最高：隐私保护
            PromptInjectionRule(),     # 优先级高：安全防御
            NightCurfewRule(),         # 优先级中：时间风控
            SensitiveLocationRule(),   # 优先级中：地点风控
            FinancialTransactionRule()  # 优先级低：业务流程
        ]

    def evaluate_all(self, state: Dict[str, Any]) -> RuleResult:
        """执行责任链逻辑"""
        final_decision = RuleResult(ActionType.PASS, "自动通过")

        for rule in self.rules:
            result = rule.evaluate(state)

            # 优先级 1: 如果有规则 BLOCK，直接拒绝，中断后续检查
            if result.action == ActionType.BLOCK:
                print(
                    f"🛑 [Rule] {rule.__class__.__name__} -> BLOCK: {result.reason}")
                return result

            # 优先级 2: 如果有规则 REVIEW，暂存决定，但继续检查后面有没有 BLOCK
            if result.action == ActionType.REVIEW:
                print(
                    f"⚠️ [Rule] {rule.__class__.__name__} -> REVIEW: {result.reason}")
                final_decision = result

        if final_decision.action == ActionType.PASS:
            print(f"✅ [Rule] All rules passed")

        return final_decision


# ==========================================
# 4. 便捷函数
# ==========================================

# 全局规则引擎实例
_rule_engine = None


def get_rule_engine() -> RuleEngine:
    """获取全局规则引擎单例"""
    global _rule_engine
    if _rule_engine is None:
        _rule_engine = RuleEngine()
    return _rule_engine


def evaluate_state(state: Dict[str, Any]) -> RuleResult:
    """便捷函数：评估状态"""
    return get_rule_engine().evaluate_all(state)
