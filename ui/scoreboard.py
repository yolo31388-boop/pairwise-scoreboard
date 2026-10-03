"""
计分板系统 - 核心模块

功能：
- record_kill / record_assist：正确记录击杀与助攻
- record_damage：命中、爆炸、近战伤害全部计入
- calculate_score：综合击杀/死亡/助攻/伤害/拆包，按游戏模式取分值
- mvp_voting：综合伤害、贡献与生存效率
- stat_tracking：实时统计，爆头/连杀/拆包等详细数据，退出玩家数据保留
- scoreboard_sort：按分数降序，稳定排序（平分按注册顺序）
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import time


@dataclass
class Config:
    """配置项：游戏模式及各项分值。"""
    mode: str = "casual"
    kill_score: float = 100.0
    death_penalty: float = 20.0
    assist_score: float = 25.0
    damage_score: float = 0.1
    bomb_score: float = 150.0


# 各游戏模式分值配置
MODE_CONFIGS: Dict[str, Dict[str, float]] = {
    "casual": {
        "kill_score": 100.0,
        "death_penalty": 20.0,
        "assist_score": 25.0,
        "damage_score": 0.1,
        "bomb_score": 150.0,
    },
    "competitive": {
        "kill_score": 150.0,
        "death_penalty": 30.0,
        "assist_score": 50.0,
        "damage_score": 0.2,
        "bomb_score": 200.0,
    },
    "deathmatch": {
        "kill_score": 50.0,
        "death_penalty": 10.0,
        "assist_score": 0.0,
        "damage_score": 0.05,
        "bomb_score": 0.0,
    },
}


@dataclass
class PlayerStats:
    """单个玩家的实时统计数据。"""
    player_id: str
    name: str = ""
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    damage: float = 0.0
    hits: float = 0.0
    explosive_damage: float = 0.0
    melee_damage: float = 0.0
    headshots: int = 0
    bomb_defuses: int = 0
    current_streak: int = 0
    best_streak: int = 0
    score: float = 0.0
    active: bool = True
    joined_at: float = field(default_factory=time.time)
    left_at: Optional[float] = None
    order: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "player_id": self.player_id,
            "name": self.name,
            "kills": self.kills,
            "deaths": self.deaths,
            "assists": self.assists,
            "damage": self.damage,
            "hits": self.hits,
            "explosive_damage": self.explosive_damage,
            "melee_damage": self.melee_damage,
            "headshots": self.headshots,
            "bomb_defuses": self.bomb_defuses,
            "current_streak": self.current_streak,
            "best_streak": self.best_streak,
            "score": self.score,
            "active": self.active,
        }


class ScoreboardSystem:
    """计分板系统核心类。"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        mode = self.config.get("mode", "casual")
        self.mode = mode if mode in MODE_CONFIGS else "casual"
        mode_weights = dict(MODE_CONFIGS[self.mode])
        mode_weights.update({k: v for k, v in self.config.items()
                             if k in mode_weights})
        self.weights = mode_weights
        self._state: Dict[str, PlayerStats] = {}
        self._history: List[Dict[str, Any]] = []
        self._kill_log: List[Dict[str, Any]] = []
        self._order_counter = 0

    # ------------------------------------------------------------------
    # 玩家管理
    # ------------------------------------------------------------------
    def add_player(self, player_id: str, name: str = "") -> PlayerStats:
        """注册玩家；已存在则直接返回（重复加入不会清空数据）。"""
        if player_id not in self._state:
            self._order_counter += 1
            self._state[player_id] = PlayerStats(
                player_id=player_id,
                name=name or player_id,
                order=self._order_counter,
            )
        else:
            stats = self._state[player_id]
            stats.active = True
            stats.left_at = None
        return self._state[player_id]

    def remove_player(self, player_id: str) -> None:
        """玩家中途退出：数据立即固化，不从统计中消失。"""
        stats = self._state.get(player_id)
        if stats is not None:
            stats.active = False
            stats.left_at = time.time()
            self._history.append({
                "type": "leave",
                "player_id": player_id,
                "stats": stats.to_dict(),
                "time": stats.left_at,
            })

    def get_player(self, player_id: str) -> Optional[PlayerStats]:
        return self._state.get(player_id)

    # ------------------------------------------------------------------
    # 事件记录
    # ------------------------------------------------------------------
    def record_kill(self, killer_id: str, victim_id: str,
                    headshot: bool = False) -> None:
        """记录一次击杀：击杀者 kills+1/连杀，被杀者 deaths+1/连杀中断。"""
        killer = self.add_player(killer_id)
        victim = self.add_player(victim_id)

        killer.kills += 1
        killer.current_streak += 1
        if killer.current_streak > killer.best_streak:
            killer.best_streak = killer.current_streak
        if headshot:
            killer.headshots += 1

        victim.deaths += 1
        victim.current_streak = 0

        self._refresh_score(killer)
        self._refresh_score(victim)

        event = {
            "type": "kill",
            "killer_id": killer_id,
            "victim_id": victim_id,
            "headshot": bool(headshot),
            "time": time.time(),
        }
        self._kill_log.append(event)
        self._history.append(event)

    def record_assist(self, assister_id: str, victim_id: str,
                      amount: int = 1) -> None:
        """记录助攻（可多人），助攻列表不再永远为空。"""
        if assister_id == victim_id:
            return
        assister = self.add_player(assister_id)
        self.add_player(victim_id)
        assister.assists += max(0, amount)
        self._refresh_score(assister)
        event = {
            "type": "assist",
            "assister_id": assister_id,
            "victim_id": victim_id,
            "time": time.time(),
        }
        self._history.append(event)

    def record_damage(self, attacker_id: str, target_id: str,
                      amount: float, damage_type: str = "hit") -> None:
        """记录伤害。damage_type: hit / explosive / melee，全部计入总伤害。"""
        amount = max(0.0, float(amount))
        attacker = self.add_player(attacker_id)
        self.add_player(target_id)
        attacker.damage += amount
        bucket = {
            "hit": "hits",
            "explosive": "explosive_damage",
            "melee": "melee_damage",
        }.get(damage_type, "hits")
        setattr(attacker, bucket, getattr(attacker, bucket) + amount)
        self._refresh_score(attacker)

    def record_bomb_defuse(self, player_id: str) -> None:
        """记录拆包。"""
        player = self.add_player(player_id)
        player.bomb_defuses += 1
        self._refresh_score(player)
        self._history.append({
            "type": "bomb_defuse",
            "player_id": player_id,
            "time": time.time(),
        })

    # ------------------------------------------------------------------
    # 分数计算
    # ------------------------------------------------------------------
    def _refresh_score(self, stats: PlayerStats) -> None:
        stats.score = self.calculate_score(stats.player_id)

    def calculate_score(self, player_id: str) -> float:
        """综合多维度计分，各分值由游戏模式配置决定。"""
        stats = self._state.get(player_id)
        if stats is None:
            return 0.0
        w = self.weights
        score = (
            stats.kills * w["kill_score"]
            - stats.deaths * w["death_penalty"]
            + stats.assists * w["assist_score"]
            + stats.damage * w["damage_score"]
            + stats.bomb_defuses * w["bomb_score"]
        )
        stats.score = score
        return score

    # ------------------------------------------------------------------
    # MVP 评选
    # ------------------------------------------------------------------
    def _mvp_rating(self, stats: PlayerStats) -> float:
        """贡献（分数，含击杀/助攻/拆包）加权后乘以生存效率系数。"""
        contribution = stats.score + stats.damage * self.weights["damage_score"]
        efficiency = (stats.kills + stats.assists + 1) / (stats.deaths + 1)
        return contribution * efficiency

    def mvp_voting(self) -> Optional[str]:
        """综合效率与贡献评选 MVP，返回 player_id；无玩家时返回 None。"""
        if not self._state:
            return None
        candidates = sorted(
            self._state.values(),
            key=lambda s: (self._mvp_rating(s), -s.order),
            reverse=True,
        )
        return candidates[0].player_id

    # ------------------------------------------------------------------
    # 实时数据统计
    # ------------------------------------------------------------------
    def stat_tracking(self, player_id: Optional[str] = None) -> Any:
        """实时返回统计。指定玩家返回该玩家字典（含已退出玩家），否则返回全部。"""
        if player_id is not None:
            stats = self._state.get(player_id)
            return stats.to_dict() if stats is not None else None
        return {pid: s.to_dict() for pid, s in self._state.items()}

    # ------------------------------------------------------------------
    # 排序
    # ------------------------------------------------------------------
    def scoreboard_sort(self,
                        include_inactive: bool = True) -> List[PlayerStats]:
        """按分数降序稳定排序；平分保持注册先后顺序。"""
        players = [s for s in self._state.values()
                   if include_inactive or s.active]
        return sorted(players, key=lambda s: (-s.score, s.order))

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def update(self, dt: float) -> None:
        """每帧更新：统计是实时累计的，这里只需确保分数与数据一致。"""
        for stats in self._state.values():
            stats.score = self.calculate_score(stats.player_id)

    def reset(self) -> None:
        """重置状态。"""
        self._state = {}
        self._history = []
        self._kill_log = []
        self._order_counter = 0
