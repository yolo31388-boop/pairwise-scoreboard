"""
计分板系统 - 核心模块（已修复）

修复内容：
- record_kill() 正确归属击杀/死亡，并记录助攻
- calculate_score() 综合击杀/死亡/助攻/伤害/爆头/连杀/拆包，按模式配置分值
- mvp_voting() 综合贡献分与效率（伤害/死亡），统计全部伤害类型
- stat_tracking() 实时统计，玩家中途退出数据不丢失，含爆头/连杀/拆包
- scoreboard_sort() 按分数排序，平局确定性打破，结果稳定
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import time


# 各游戏模式的分值配置（可被 config["mode_configs"] 覆盖）
DEFAULT_MODE_CONFIGS: Dict[str, Dict[str, float]] = {
    "deathmatch": {
        "kill": 100, "assist": 50, "damage": 0.2,
        "death": -25, "headshot": 10, "streak": 20, "defuse": 0,
    },
    "bomb_defusal": {
        "kill": 100, "assist": 40, "damage": 0.1,
        "death": -20, "headshot": 10, "streak": 15, "defuse": 300,
    },
    "casual": {
        "kill": 50, "assist": 25, "damage": 0.1,
        "death": 0, "headshot": 5, "streak": 10, "defuse": 100,
    },
}

DEFAULT_MODE = "deathmatch"

# 所有计入总伤害的伤害类型
DAMAGE_TYPES = ("bullet", "explosion", "melee")


@dataclass
class Config:
    """配置项"""
    pass


@dataclass
class PlayerStats:
    """单个玩家的实时统计"""
    name: str
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    damage: float = 0.0
    damage_by_type: Dict[str, float] = field(default_factory=dict)
    headshots: int = 0
    current_streak: int = 0
    max_streak: int = 0
    defuses: int = 0
    active: bool = True
    quit_at: Optional[float] = None


class ScoreboardSystem:
    """计分板系统核心类"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._state: Dict[str, PlayerStats] = {}
        self._history: List[Dict] = []
        self._mode = self.config.get("mode", DEFAULT_MODE)
        self._mode_configs = dict(DEFAULT_MODE_CONFIGS)
        self._mode_configs.update(self.config.get("mode_configs", {}))

    # ------------------------------------------------------------------
    # 基础接口（保持原有 API 不变）
    # ------------------------------------------------------------------
    def update(self, dt: float):
        """每帧更新（统计为实时写入，无需在此做批处理）"""
        pass

    def reset(self):
        """重置状态"""
        self._state = {}
        self._history = []

    # ------------------------------------------------------------------
    # 玩家管理
    # ------------------------------------------------------------------
    def add_player(self, name: str):
        """玩家加入比赛"""
        if name not in self._state:
            self._state[name] = PlayerStats(name=name)
        else:
            self._state[name].active = True
            self._state[name].quit_at = None

    def player_quit(self, name: str):
        """玩家中途退出：归档快照，数据不丢失"""
        stats = self._require(name)
        stats.active = False
        stats.quit_at = time.time()
        self._history.append({
            "event": "quit",
            "player": name,
            "snapshot": self.stat_tracking(name),
            "time": stats.quit_at,
        })

    # ------------------------------------------------------------------
    # 事件记录（实时统计）
    # ------------------------------------------------------------------
    def record_kill(self, killer: Optional[str], victim: str,
                    assists: Optional[List[str]] = None,
                    headshot: bool = False,
                    damage: float = 0.0,
                    damage_type: str = "bullet"):
        """记录一次击杀：击杀者+1杀，被杀者+1死，助攻者+1助攻

        killer 为 None 时表示无归属的死亡（如坠亡），只统计死亡。
        """
        victim_stats = self._ensure(victim)

        killer_stats = self._ensure(killer) if killer is not None else None
        if killer_stats is not None:
            killer_stats.kills += 1
            killer_stats.current_streak += 1
            killer_stats.max_streak = max(killer_stats.max_streak,
                                          killer_stats.current_streak)
            if headshot:
                killer_stats.headshots += 1

        victim_stats.deaths += 1
        victim_stats.current_streak = 0

        for assistant in assists or []:
            if assistant != killer and assistant != victim:
                self._ensure(assistant).assists += 1

        if damage and killer is not None:
            self.record_damage(killer, damage, damage_type)

        self._history.append({
            "event": "kill", "killer": killer, "victim": victim,
            "assists": list(assists or []), "headshot": headshot,
            "time": time.time(),
        })

    def record_damage(self, attacker: str, amount: float,
                      damage_type: str = "bullet"):
        """记录伤害：命中、爆炸、近战等所有类型都计入总伤害"""
        if damage_type not in DAMAGE_TYPES:
            raise ValueError(f"未知伤害类型: {damage_type}")
        stats = self._ensure(attacker)
        stats.damage += amount
        stats.damage_by_type[damage_type] = \
            stats.damage_by_type.get(damage_type, 0.0) + amount

    def record_defuse(self, player: str):
        """记录一次拆包"""
        self._ensure(player).defuses += 1
        self._history.append({
            "event": "defuse", "player": player, "time": time.time(),
        })

    # ------------------------------------------------------------------
    # 分数计算
    # ------------------------------------------------------------------
    def calculate_score(self, player: str,
                        mode: Optional[str] = None) -> float:
        """综合多维度计算分数，分值按游戏模式配置"""
        stats = self._require(player)
        weights = self._mode_configs[mode or self._mode]
        score = (
            stats.kills * weights["kill"]
            + stats.assists * weights["assist"]
            + stats.damage * weights["damage"]
            + stats.deaths * weights["death"]
            + stats.headshots * weights["headshot"]
            + stats.max_streak * weights["streak"]
            + stats.defuses * weights["defuse"]
        )
        return score

    # ------------------------------------------------------------------
    # MVP 评选
    # ------------------------------------------------------------------
    def mvp_voting(self) -> Optional[str]:
        """综合贡献分与效率（伤害/死亡）评选 MVP"""
        candidates = [s for s in self._state.values()
                      if s.kills + s.assists + s.defuses > 0 or s.damage > 0]
        if not candidates:
            return None

        def rating(stats: PlayerStats) -> float:
            efficiency = stats.damage / max(stats.deaths, 1)
            return self.calculate_score(stats.name) + efficiency

        best = max(candidates, key=lambda s: (rating(s), s.name))
        return best.name

    # ------------------------------------------------------------------
    # 数据统计
    # ------------------------------------------------------------------
    def stat_tracking(self, player: Optional[str] = None):
        """实时统计快照；指定玩家返回该玩家数据，否则返回全部"""
        def snapshot(stats: PlayerStats) -> Dict:
            return {
                "name": stats.name,
                "kills": stats.kills,
                "deaths": stats.deaths,
                "assists": stats.assists,
                "damage": stats.damage,
                "damage_by_type": dict(stats.damage_by_type),
                "headshots": stats.headshots,
                "current_streak": stats.current_streak,
                "max_streak": stats.max_streak,
                "defuses": stats.defuses,
                "score": self.calculate_score(stats.name),
                "active": stats.active,
            }

        if player is not None:
            return snapshot(self._require(player))
        return {name: snapshot(stats) for name, stats in self._state.items()}

    # ------------------------------------------------------------------
    # 计分板排序
    # ------------------------------------------------------------------
    def scoreboard_sort(self) -> List[Dict]:
        """按分数降序排序；平局按击杀数、再按名字确定性打破，结果稳定"""
        rows = [self.stat_tracking(name) for name in self._state]
        rows.sort(key=lambda r: (-r["score"], -r["kills"], r["name"]))
        return rows

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _ensure(self, name: str) -> PlayerStats:
        if name not in self._state:
            self._state[name] = PlayerStats(name=name)
        return self._state[name]

    def _require(self, name: str) -> PlayerStats:
        if name not in self._state:
            raise KeyError(f"未知玩家: {name}")
        return self._state[name]
