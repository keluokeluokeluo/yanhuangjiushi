# 沿黄九市高质量发展研究：可运行代码与分析报告

依据随包《思路.docx》实施，未加入耦合协调度模型。原始数据为用户上传文件，无外部下载、API或密钥依赖。

## 快速运行

建议 Python 3.12（本次实测3.12.14），先解压整个目录。

macOS / Linux：

```bash
cd yanhuang_analysis
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python analysis.py
.venv/bin/python -m unittest -v
```

Windows PowerShell：

```powershell
cd yanhuang_analysis
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe analysis.py
.\.venv\Scripts\python.exe -m unittest -v
```

安装依赖需要访问PyPI，执行分析本身离线可用。已有固定版本依赖时可直接 `python analysis.py`。脚本按自身位置寻找数据，不依赖终端当前路径。可指定：

```bash
python analysis.py --input data/input.xlsx --output output_new
```

中文图表优先使用Noto CJK字体；若本机未安装，安装Noto Sans CJK后重跑可获得完整中文显示。没有该字体也可生成计算结果和Word报告。云环境已装字体且图表已检查。

## 包内内容

- `analysis.py`：数据检查、全样本标准化、熵权、CRITIC、博弈组合、综合与四子系统TOPSIS、逐年Dagum分解、CV、带宽敏感性核密度、指标及子系统障碍度、6种旅游指标敏感性情景、自动生成报告。
- `test_analysis.py`：6项测试，包括已知交叉/非交叉分布的Dagum解析结果、排列/尺度不变性、TOPSIS理想点、KDE面积、实际面板完整性与原始异常值保留检查。
- `requirements.txt`：本次运行版本固定。
- `data/input.xlsx`：原始Excel字节副本；`data/思路.docx`：研究方案原文。
- `output/分析报告.docx`、`output/分析报告.md`：中文报告，包含公式、完整方法口径、结果表、图、局限和政策含义。
- `output/全部实证结果.xlsx`：清洗面板、核查清单、标准化值、三套权重、全部城市年度得分及排名、年度与区域均值、55组年度Dagum分解与CV、城市/区域/年份障碍度和敏感性结果。
- `output/*.csv`：对应中间表，UTF-8 BOM编码，便于Excel读取。
- `output/01_*.png`至`05_*.png`：趋势、热力图、Dagum/CV、核密度、障碍度。
- `output/运行核验.json`：输入SHA256、组合系数、数值检查、版本；`测试记录.txt`：实际测试记录。

## 数据与方法约定

1. 指定九市×2013—2023年，99条，11项；缺失、重复、不完整面板会明确报错，未静默插补。新数据需要相同表头和研究范围；拓展年份应同时修改研究设计及代码常量。
2. 基准保留原始值。特别关注济南2015年旅游11.9、德州2020年旅游0、九市2023年排放与2022年完全重复。能耗与旅游单位未知，需回查统计来源；未虚构口径或来源。
3. 正负向极差标准化及权重在全部99条上固定。负向为单位GDP能耗、颗粒物排放；医疗和图书已分别为每千人/每万人指标。保留专利和景区总量指标，揭示其规模效应限制。
4. TOPSIS先以权重乘标准化矩阵再计算欧氏距离；子系统内部重新归一化权重。具体公式及游戏组合的退化处理见报告。不得混用另一种加权距离定义。
5. Dagum地域为文档中的研究性分组，非官方区划；城市等权。核密度每年仅9条，采用[0,1]反射边界及0.5/1/1.5倍Silverman带宽。CV采用总体标准差ddof=0。
6. 障碍度不是因果效应。总体/区域障碍度为城市障碍度平均。旅游插值与剔除等仅为敏感性情景，不当作已确认修正。
7. 数据更新后所有输出由代码同步重算。报告无外部文献综述或来源核验，不应当作无需复核即可提交的最终学位论文。

## 本次实测

已从输入完整运行，生成99条综合与四子系统得分、55组Dagum分解（11年×5类指数）以及6个敏感性情景；权重/得分/障碍度/分解加总检查通过，6项单元测试通过。再运行得到同样的CSV与核验摘要（Word/Excel容器时间戳可能变化）。
