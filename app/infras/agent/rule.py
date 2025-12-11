from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, Any, Optional
from datetime import datetime

# --- 基础定义 ---


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


class BaseRule(ABC):
    """规则基类 (策略模式接口)"""
    @abstractmethod
    def evaluate(self, tool_name: str, args: Dict[str, Any]) -> RuleResult:
        pass

# --- 具体业务规则 (可随时扩展) ---


class NightCurfewRule(BaseRule):
    """规则示例1: 夜间风控 (23:00 - 06:00 禁止订票)"""

    def evaluate(self, tool_name: str, args: Dict[str, Any]) -> RuleResult:
        # 只针对预订类工具
        if not tool_name.startswith("book_"):
            return RuleResult(ActionType.PASS)

        current_hour = datetime.now().hour
        if current_hour >= 23 or current_hour < 6:
            return RuleResult(ActionType.BLOCK, "系统维护时间 (23:00-06:00) 禁止下单")
        return RuleResult(ActionType.PASS)


class HighAmountRule(BaseRule):
    """规则示例2: 大额预警 (模拟: 假如 args 里有价格，超过 5000 需审批)"""

    def evaluate(self, tool_name: str, args: Dict[str, Any]) -> RuleResult:
        if tool_name == "book_flight":
            # 这里为了演示，假设所有机票都需要审批
            # 实际业务中，你可以去查数据库获取价格
            return RuleResult(ActionType.REVIEW, "机票预订涉及资金交易，默认需人工确认")
        return RuleResult(ActionType.PASS)


class SensitiveLocationRule(BaseRule):
    """规则示例3: 敏感地点拦截"""

    def evaluate(self, tool_name: str, args: Dict[str, Any]) -> RuleResult:
        if "to_airport" in args and args["to_airport"] == "XXX":
            return RuleResult(ActionType.BLOCK, "目的地处于高风险地区，禁止预订")
        return RuleResult(ActionType.PASS)

# --- 规则管理器 ---


class RuleEngine:
    """规则引擎：管理并执行所有规则"""

    def __init__(self):
        # 注册你的规则
        self.rules = [
            NightCurfewRule(),
            SensitiveLocationRule(),
            HighAmountRule(),
        ]

    def evaluate_all(self, tool_name: str, args: Dict[str, Any]) -> RuleResult:
        """执行责任链逻辑"""
        final_decision = RuleResult(ActionType.PASS, "自动通过")

        for rule in self.rules:
            result = rule.evaluate(tool_name, args)

            # 优先级 1: 如果有规则 BLOCK，直接拒绝，中断后续检查
            if result.action == ActionType.BLOCK:
                return result

            # 优先级 2: 如果有规则 REVIEW，暂存决定，但继续检查后面有没有 BLOCK
            if result.action == ActionType.REVIEW:
                final_decision = result

        return final_decision
