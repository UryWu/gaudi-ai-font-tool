# 制作个人字库全流程

> 本文档整理制作个人书法字库 TTF 的完整工作流，从手写拍照到 AI 补全生僻字，串联两个独立工具协同完成。

## 工具组合（按阶段）

| 阶段 | 工具 | 作用 | 端口 | 链接 |
|------|------|------|------|------|
| 拍照 | 手机 + 纸笔 | 手写 + 拍摄 | — | — |
| 切割 / 校正 / 标注 / 导出 | **高迪书法字库预处理工具**（gaudi-font-preprocess） | 把书法长篇图切成单字 PNG | **7500** | https://github.com/UryWu/gaudi-font-preprocess |
| PNG → TTF | FontLab / FontForge / fontTools | 把命好名的 PNG 合成字体文件 | — | 桌面软件 |
| 训练 / 生成 / 验证 | **本项目**（gaudi-ai-font-tool） | LoRA 微调 + 生僻字 AI 生成 + OCR 筛选 | **7550** | https://github.com/UryWu/gaudi-ai-font-tool |

> **核心要点：**
> - **步骤 ②③④⑤** 全部在 `gaudi-font-preprocess`（端口 7500）里完成
> - **步骤 ⑦** 在本项目（端口 7550）里完成
> - 步骤 ①⑥ 不依赖任何软件（手写拍照 + FontLab GUI / 桌面工具）

## 全流程概览

```
[手写拍照]   纸笔 + 手机                 ← 无软件
       ↓
[gaudi-font-preprocess (7500)]   切割/校正/标注/导出   ← 步骤 ②③④⑤
       ↓
FontLab 标准命名的字符 PNG（uni4E00_一.png）
       ↓
[FontLab / FontForge / fontTools]   PNG → TTF           ← 步骤 ⑥
       ↓
你的个人字库.ttf   ← 这才是「学习字库」
       ↓
[本项目 (7550)]   训练 + 生成生僻字      ← 步骤 ⑦
```

## 具体步骤

### ① 准备素材（手动，无软件）

- **不写单字格**：日常长篇创作（日积月累）更适合做字库素材，而不是枯燥填格
- 写完后用手机拍摄高清照（约 1/6 四尺对开）
- 拍摄时光线均匀、字迹清晰
- **本步骤不依赖任何软件**

### ② 切割布局（gaudi-font-preprocess 7500）

**工具：gaudi-font-preprocess（端口 7500）**

- 上传第 ① 步得到的图片
- 软件自动检测行列切割线
- 可手动拖动切割线调整位置，Shift+双击添加新切割线

### ③ 切割调整（gaudi-font-preprocess 7500）

**工具：gaudi-font-preprocess（端口 7500）**

- 逐字检查切割结果
- 删除噪点、错字、空白切片

### ④ 缩放校正（gaudi-font-preprocess 7500）

**工具：gaudi-font-preprocess（端口 7500）**

- 统一字符像素尺寸
- 自动居中排版

### ⑤ 标注出图（gaudi-font-preprocess 7500）

**工具：gaudi-font-preprocess（端口 7500）**

- 三种标注模式可选：
  - **繁简混合**
  - **以简为主**
  - **以繁为主**
- 支持批量标注和手动逐字标注
- 导出后自动清理中间文件
- 命名规范：BMP 字符 `uniXXXX`，扩展区字符 `uXXXXX`

### ⑥ PNG → TTF（FontLab / FontForge / fontTools）

**工具：FontLab / FontForge GUI，或 fontTools Python 脚本**

把第 ⑤ 步导出的字符 PNG 合成字体文件：

- **FontLab / FontForge**：GUI 操作，导入 PNG + 设置度量 + 导出 TTF
- **fontTools**：Python 脚本化（适合批量或 CI 流）
- 命名格式建议遵循 FontLab 标准（`uni4E00` / `u20000` 等）

> 💡 **本项目已自带脚本**：`scripts/build_variant_ttf.py` 能从「基础字体 + PNG 素材目录」直接
> 构建 TTF，而且**能把同一个字的多份手写（如「的」25 种写法）全部装进同一个字体** ——
> 标准 cmap 一对一映射装不下变体，它会把变体挂到 PUA 码点上。
> 这一路由 FontLab 手工做会丢掉全部变体。详见 [font-variants.md](font-variants.md)。

### ⑦ AI 补全生僻字（本项目 7550）

**工具：本项目 gaudi-ai-font-tool（端口 7550）**

得到的 `个人字库.ttf` 即「学习字库」：

1. 打开本项目（7550），在「训练页」填写：
   - 基础模型：项目 `model/zi2zi-JiT-B-16.pth`
   - 源字体：项目 `font/default.ttf`
   - **学习字库TTF**：你的 `个人字库.ttf` ← 关键输入
   - 输出目录：训练产物存放地
2. 点击「准备数据」→「开始训练」，得到 `checkpoint-last.pth`
3. 切换到「字库生字」页，喂入需要补全的生僻字（CMAP 外的字符），AI 会按你的书法风格生成字形图片
4. 「OCR 页」批量识别 + 置信度筛选，保留可用字形

详见 [docs/output-directory.md](output-directory.md)（训练/生成页的输出目录含义）。

## 实战建议（来自配套工具 README 作者）

- **不写单字格**：日常长篇创作（日积月累）更适合做字库素材
- **书写质量不稳定**：自由筛选优质字迹，软件逐字检查
- **古典繁体为主**：所以「繁简混合」+ CJK 扩展区支持很关键
- **GB2312（6763字）够日常**，**GBK（20902字）才覆盖生僻字**
- **AI 局限**：当前 AI 生成字错误率高，多重迭代后仅 ~60% 勉强可用；最终方案是手动补写缺失字（如作者手动补 4000+ 字达到 GBK）

## 入门方式

**最简入手：** 从 https://github.com/UryWu/gaudi-font-preprocess/releases 下载独立运行版 zip，解压后双击 `启动.bat` 即可使用，无需安装 Python 及任何依赖。

**从源码运行：**

```bash
git clone https://github.com/UryWu/gaudi-font-preprocess.git
cd gaudi-font-preprocess
pip install -r requirements.txt
python app.py
# 访问 http://localhost:7500
```

本项目（7550）的启动方式见 [README.md](../README.md) 与项目根目录的 `start-ai-font-port-7550.bat`（或 PowerShell 版 `start-ai-font-port-7550.ps1`）。