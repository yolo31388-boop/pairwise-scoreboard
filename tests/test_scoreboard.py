"""
计分板系统 - 验收测试

运行方式：python -m pytest tests/test_scoreboard.py -q
共 12 个测试用例（pytest 与 unittest 均可运行）
"""
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.scoreboard import ScoreboardSystem, MODE_CONFIGS


class TestScoreboardSystem(unittest.TestCase):
    """计分板系统测试套件"""

    def setUp(self):
        """每个测试前的初始化"""
        self.system = ScoreboardSystem()

    def test_case_01(self):
        """击杀记录：击杀者与被杀者不能搞反"""
        self.system.record_kill("alice", "bob")
        alice = self.system.get_player("alice")
        bob = self.system.get_player("bob")
        self.assertEqual(alice.kills, 1)
        self.assertEqual(alice.deaths, 0)
        self.assertEqual(bob.kills, 0)
        self.assertEqual(bob.deaths, 1)
        self.system.record_kill("bob", "alice")
        self.assertEqual(self.system.get_player("alice").kills, 1)
        self.assertEqual(self.system.get_player("alice").deaths, 1)
        self.assertEqual(self.system.get_player("bob").kills, 1)
        self.assertEqual(self.system.get_player("bob").deaths, 1)

    def test_case_02(self):
        """助攻记录：助攻列表不能永远为空，且支持多人助攻"""
        self.system.record_kill("alice", "bob")
        self.system.record_assist("carol", "bob")
        self.system.record_assist("dave", "bob")
        self.assertEqual(self.system.get_player("carol").assists, 1)
        self.assertEqual(self.system.get_player("dave").assists, 1)
        self.system.record_assist("carol", "dave")
        self.assertEqual(self.system.get_player("carol").assists, 2)
        self.assertEqual(self.system.get_player("alice").assists, 0)
        self.assertTrue(
            any(e["type"] == "assist" for e in self.system._history)
        )

    def test_case_03(self):
        """伤害统计：命中、爆炸、近战伤害全部计入总伤害"""
        self.system.record_damage("alice", "bob", 100, "hit")
        self.system.record_damage("alice", "bob", 50, "explosive")
        self.system.record_damage("alice", "bob", 30, "melee")
        alice = self.system.get_player("alice")
        self.assertEqual(alice.hits, 100)
        self.assertEqual(alice.explosive_damage, 50)
        self.assertEqual(alice.melee_damage, 30)
        self.assertEqual(alice.damage, 180)

    def test_case_04(self):
        """分数计算：综合击杀/死亡/助攻/伤害/拆包，而非只看击杀"""
        for _ in range(2):
            self.system.record_kill("alice", "bob")
        self.system.record_kill("bob", "alice")
        self.system.record_assist("carol", "alice")
        self.system.record_damage("alice", "bob", 100, "hit")
        self.system.record_bomb_defuse("alice")
        # 2*100 - 1*20 + 0 + 100*0.1 + 1*150 = 340
        self.assertEqual(self.system.calculate_score("alice"), 340.0)
        # carol: 0 击杀也能有助攻分
        self.assertEqual(self.system.calculate_score("carol"), 25.0)

    def test_case_05(self):
        """模式配置：不同游戏模式击杀等分值不同"""
        def build(system):
            for _ in range(2):
                system.record_kill("alice", "bob")
            system.record_kill("bob", "alice")
            system.record_assist("carol", "alice")
            system.record_damage("alice", "bob", 100, "hit")
            system.record_bomb_defuse("alice")

        casual = ScoreboardSystem({"mode": "casual"})
        build(casual)
        comp = ScoreboardSystem({"mode": "competitive"})
        build(comp)
        # 2*150 - 30 + 20 + 200 = 490
        self.assertEqual(comp.calculate_score("alice"), 490.0)
        self.assertEqual(casual.calculate_score("alice"), 340.0)
        self.assertNotEqual(
            comp.calculate_score("alice"), casual.calculate_score("alice")
        )
        self.assertEqual(comp.mode, "competitive")

    def test_case_06(self):
        """自定义分值：配置覆盖模式默认值，击杀分值不再写死 100"""
        system = ScoreboardSystem({"mode": "casual", "kill_score": 10.0})
        system.record_kill("alice", "bob")
        self.assertEqual(system.calculate_score("alice"), 10.0)
        self.assertEqual(system.weights["kill_score"], 10.0)
        dm = ScoreboardSystem({"mode": "deathmatch"})
        dm.record_kill("alice", "bob")
        self.assertEqual(dm.calculate_score("alice"), 50.0)

    def test_case_07(self):
        """MVP：500 伤害 0 死亡的人应胜过 1000 伤害 10 死亡的人"""
        for _ in range(10):
            self.system.record_kill("sprayer", "bot1")
            self.system.record_kill("bot1", "sprayer")
        for _ in range(10):
            self.system.record_kill("efficient", "bot2")
        self.system.record_damage("sprayer", "bot1", 1000, "hit")
        self.system.record_damage("efficient", "bot2", 500, "hit")
        self.assertEqual(self.system.mvp_voting(), "efficient")

    def test_case_08(self):
        """MVP：不能只看伤害量，一枪没开的人不得当 MVP；无玩家返回 None"""
        self.system.record_damage("trash", "bot1", 2000, "explosive")
        for _ in range(10):
            self.system.record_kill("bot1", "trash")
        self.system.record_kill("star", "bot2")
        self.system.record_damage("star", "bot2", 100, "hit")
        mvp = self.system.mvp_voting()
        self.assertNotEqual(mvp, "trash")
        self.assertEqual(mvp, "bot1")
        self.assertIsNone(ScoreboardSystem().mvp_voting())

    def test_case_09(self):
        """数据统计：比赛进行中即可实时读取，无需等比赛结束"""
        self.system.record_kill("alice", "bob")
        mid = self.system.stat_tracking("alice")
        self.assertIsNotNone(mid)
        self.assertEqual(mid["kills"], 1)
        self.assertEqual(mid["deaths"], 0)
        self.system.record_kill("alice", "carol")
        mid2 = self.system.stat_tracking("alice")
        self.assertEqual(mid2["kills"], 2)
        all_stats = self.system.stat_tracking()
        self.assertEqual(set(all_stats.keys()), {"alice", "bob", "carol"})

    def test_case_10(self):
        """中途退出玩家的数据不能丢失"""
        for _ in range(3):
            self.system.record_kill("leaver", "bob")
        self.system.record_assist("leaver", "carol")
        snapshot = self.system.stat_tracking("leaver")
        self.system.remove_player("leaver")
        after = self.system.stat_tracking("leaver")
        self.assertIsNotNone(after)
        self.assertEqual(after["kills"], snapshot["kills"])
        self.assertEqual(after["assists"], 1)
        self.assertFalse(after["active"])
        ids = [p.player_id for p in self.system.scoreboard_sort()]
        self.assertIn("leaver", ids)
        ids_active = [p.player_id
                      for p in self.system.scoreboard_sort(include_inactive=False)]
        self.assertNotIn("leaver", ids_active)

    def test_case_11(self):
        """详细统计：爆头数、连杀数、拆包数都要记录"""
        self.system.record_kill("alice", "bob", headshot=True)
        self.system.record_kill("alice", "carol", headshot=True)
        self.system.record_kill("alice", "dave")
        alice = self.system.get_player("alice")
        self.assertEqual(alice.headshots, 2)
        self.assertEqual(alice.current_streak, 3)
        self.assertEqual(alice.best_streak, 3)
        self.system.record_kill("bob", "alice")
        self.assertEqual(self.system.get_player("alice").current_streak, 0)
        self.assertEqual(self.system.get_player("alice").best_streak, 3)
        self.system.record_bomb_defuse("alice")
        self.assertEqual(self.system.get_player("alice").bomb_defuses, 1)

    def test_case_12(self):
        """排序：按分数降序，平分时顺序稳定可复现"""
        self.system.add_player("p1")
        self.system.add_player("p2")
        self.system.add_player("p3")
        # p3 最高分；p1、p2 分数相同（均为 0），按注册顺序 p1 在 p2 前
        self.system.record_kill("p3", "victim")
        ordered = [p.player_id for p in self.system.scoreboard_sort()]
        self.assertEqual(ordered[0], "p3")
        self.assertLess(ordered.index("p1"), ordered.index("p2"))
        # 多次排序结果一致（稳定）
        again = [p.player_id for p in self.system.scoreboard_sort()]
        self.assertEqual(ordered, again)
        scores = [p.score for p in self.system.scoreboard_sort()]
        self.assertEqual(scores, sorted(scores, reverse=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
