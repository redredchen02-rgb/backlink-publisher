# 质量优化计划

本计划记录代码质量自动化和优化行动。

## 已实施的自动化

- 覆盖率阈值 85% (`p.coveragerc`)
- 单体预算检查 (`scripts/check_monolith_budget.py`)
- 导入合规检查 (`scripts/check_imports.py`)

## 运行检查

本地：
```bash
pytest --cov=src/backlink_publisher --cov-report=term-missing
python scripts/check_monolith_budget.py
python scripts/check_imports.py
```

CI 集成待添加。
