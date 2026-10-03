"""
计分板系统 - 验收测试

运行方式：python -m pytest tests/test_scoreboard.py -q
共 12 个测试用例
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.scoreboard import ScoreboardSystem


class TestScoreboardSystem:
    """计分板系统测试套件"""

    def setup_method(self):
        """每个测试前的初始化（默认 deathmatch 模式）"""
        self.system = ScoreboardSystem()

    def test_case_01(self):
        """击杀正确归属：击杀者+1杀，被杀者+1死，不能搞反"""
        self.system.record_kill("alice", "bob")
        alice = self.system.stat_tracking("alice")
        bob = self.system.stat_tracking("bob")
        assert alice["kills"] == 1 and alice["deaths"] == 0
        assert bob["deaths"] == 1 and bob["kills"] == 0

    def test_case_02(self):
        """助攻被正确记录，助攻列表不再为空"""
        self.system.record_kill("alice", "bob", assists=["carol", "dave"])
        assert self.system.stat_tracking("carol")["assists"] == 1
        assert self.system.stat_tracking("dave")["assists"] == 1
        event = self.system._history[-1]
        assert event["event"] == "kill"
        assert event["assists"] == ["carol", "dave"]

    def test_case_03(self):
        """伤害统计覆盖全部类型：命中、爆炸、近战都计入总伤害"""
        self.system.record_damage("alice", 50, "bullet")
        self.system.record_damage("alice", 80, "explosion")
        self.system.record_damage("alice", 30, "melee")
        stats = self.system.stat_tracking("alice")
        assert stats["damage"] == 160
        assert stats["damage_by_type"] == {
            "bullet": 50, "explosion": 80, "melee": 30,
        }

    def test_case_04(self):
        """分数综合多维度：击杀/助攻/伤害/爆头/连杀/死亡/拆包"""
        s = ScoreboardSystem({"mode": "bomb_defusal"})
        s.record_kill("alice", "bob", assists=["carol"], headshot=True,
                      damage=100)
        s.record_kill("alice", "dave")
        s.record_defuse("alice")
        # 2*100 + 100*0.1 + 10 + 2*15 - 0 + 300 = 550
        assert s.calculate_score("alice") == 550
        # carol 只有 1 助攻：40
        assert s.calculate_score("carol") == 40
        # bob 死 1 次：-20
        assert s.calculate_score("bob") == -20

    def test_case_05(self):
        """分值按模式配置：不同模式击杀分值不同，且支持自定义覆盖"""
        s = ScoreboardSystem({"mode": "casual"})
        s.record_kill("alice", "bob")
        # casual：击杀 50 + 1 连杀 10 = 60
        assert s.calculate_score("alice") == 60
        # deathmatch：击杀 100 + 1 连杀 20 = 120
        assert s.calculate_score("alice", mode="deathmatch") == 120

        custom = ScoreboardSystem({
            "mode": "custom",
            "mode_configs": {"custom": {
                "kill": 200, "assist": 10, "damage": 0,
                "death": 0, "headshot": 0, "streak": 0, "defuse": 0,
            }},
        })
        custom.record_kill("alice", "bob")
        assert custom.calculate_score("alice") == 200

    def test_case_06(self):
        """MVP 考虑效率：500 伤害 0 死胜过 1000 伤害 10 死"""
        s = self.system
        # sprayer：1 杀 10 死，1000 伤害
        s.record_kill("sprayer", "victim", damage=1000)
        for i in range(10):
            s.record_kill(f"killer{i}", "sprayer")
        # sniper：1 杀 0 死，500 伤害
        s.record_kill("sniper", "victim", damage=500)
        assert s.stat_tracking("sprayer")["deaths"] == 10
        assert s.mvp_voting() == "sniper"

    def test_case_07(self):
        """MVP 综合贡献与效率，不只看伤害量"""
        s = self.system
        # farmer：伤害最高但毫无击杀贡献
        s.record_damage("farmer", 900)
        # hero：5 杀 500 伤害
        for i in range(5):
            s.record_kill("hero", "bot", damage=100)
        assert s.stat_tracking("farmer")["damage"] == 900
        assert s.mvp_voting() == "hero"

    def test_case_08(self):
        """统计实时更新：比赛进行中即可查询，无需等比赛结束"""
        self.system.record_kill("alice", "bob")
        stats = self.system.stat_tracking("alice")
        assert stats["kills"] == 1
        assert stats["score"] == 100 + 20  # 击杀 100 + 1 连杀 20
        self.system.record_kill("alice", "carol")
        assert self.system.stat_tracking("alice")["kills"] == 2

    def test_case_09(self):
        """中途退出的玩家数据不丢失"""
        s = self.system
        s.record_kill("alice", "bob", damage=80)
        s.player_quit("alice")
        s.record_kill("carol", "bob")
        stats = s.stat_tracking("alice")
        assert stats["kills"] == 1
        assert stats["damage"] == 80
        assert stats["active"] is False
        names = [row["name"] for row in s.scoreboard_sort()]
        assert "alice" in names

    def test_case_10(self):
        """详细统计：爆头数、当前/最高连杀、拆包数"""
        s = ScoreboardSystem({"mode": "bomb_defusal"})
        s.record_kill("alice", "b1", headshot=True)
        s.record_kill("alice", "b2", headshot=True)
        s.record_kill("alice", "b3")
        s.record_kill("carol", "alice")  # 连杀中断
        s.record_kill("alice", "b4")
        s.record_defuse("alice")
        stats = s.stat_tracking("alice")
        assert stats["headshots"] == 2
        assert stats["max_streak"] == 3
        assert stats["current_streak"] == 1
        assert stats["defuses"] == 1

    def test_case_11(self):
        """计分板按分数排序，而不是只按击杀数"""
        s = ScoreboardSystem({"mode": "bomb_defusal"})
        # bob：3 杀但 10 死，分数低
        for i in range(3):
            s.record_kill("bob", f"victim{i}")
        for i in range(10):
            s.record_kill(f"killer{i}", "bob")
        # alice：1 杀 1 拆包，分数高
        s.record_kill("alice", "victim9")
        s.record_defuse("alice")
        board = s.scoreboard_sort()
        assert board[0]["name"] == "alice"
        assert s.calculate_score("alice") > s.calculate_score("bob")
        assert s.stat_tracking("bob")["kills"] > s.stat_tracking("alice")["kills"]

    def test_case_12(self):
        """排序稳定且确定：同分平局按击杀数、再按名字打破，reset 清空状态"""
        s = self.system
        s.record_kill("zoe", "bot")
        s.record_kill("amy", "bot")
        # 两人同分同击杀，按名字排序且多次调用结果一致
        first = [r["name"] for r in s.scoreboard_sort()]
        for _ in range(5):
            assert [r["name"] for r in s.scoreboard_sort()] == first
        assert first.index("amy") < first.index("zoe")

        s.reset()
        assert s.stat_tracking() == {}
        assert s.scoreboard_sort() == []
        assert s.mvp_voting() is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
