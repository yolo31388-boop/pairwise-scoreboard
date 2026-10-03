# 计分板系统

## 项目描述

计分板系统的bug修复项目。核心模块 `ui/scoreboard.py` 存在多个已知bug，需要修复后使测试全部通过。

## 已知问题

- 击杀记录搞反助攻为空
- 分数只算击杀不按模式配置
- MVP只看伤害不考虑效率
- 统计只在结束算退出丢失
- 排序只按击杀不稳定

## 项目结构

```
├── ui/scoreboard.py       # 核心模块（带bug）
├── tests/test_scoreboard.py    # 验收测试（红态）
├── pyproject.toml          # 项目配置
└── README.md               # 说明文档
```

## 运行测试

```bash
python -m pytest tests/test_scoreboard.py -q
```

修复目标：所有 12 个测试全部通过。

## 技术要求

- 纯Python标准库，不引入第三方依赖
- 不修改测试文件
- 保持现有API接口不变
- 修复所有已知bug
