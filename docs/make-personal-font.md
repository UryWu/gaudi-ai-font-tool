# 制作个人字库全流程

> 本文档整理制作个人书法字库 TTF 的完整工作流，从手写拍照到 AI 补全生僻字，串联两个独立工具协同完成。

## 工具组合

| 工具 | 作用 | 端口 | 链接 |
|------|------|------|------|
| 高迪书法字库预处理工具 | 切割布局、切割调整、缩放校正、标注出图 | 7500 | https://github.com/gaudi1209/gaudi-font-preprocess |
| 本项目（AI 字体工具） | 训练模型、生成生僻字、OCR 验证 | 7550 | https://github.com/gaudi1209/gaudi-ai-font-tool |
| FontLab / FontForge / fontTools | PNG 单字图合成 TTF 字体文件 | — | 桌面软件 |

## 全流程概览

```
手机拍摄书法作品
       ↓
[预处理工具 (7500)]        切割 / 校正 / 标注 / 导出
       ↓
FontLab 标准命名的字符 PNG（uni4E00_一.png）
       ↓
[FontLab / FontForge / fontTools]   PNG → TTF
       ↓
你的个人字库.ttf   ← 这才是「学习字库」
       ↓
[本项目 (7550)]   训练 + 生成生僻字
```

## 具体步骤

### ① 准备素材

- **不写单字格**：日常长篇创作（日积月累）更适合做字库素材，而不是枯燥填格
- 写完后用手机拍摄高清照（约 1/6 四尺对开）
- 拍摄时光线均匀、字迹清晰

工具：纸笔 + 手机

### ② 切割布局（预处理工具）

- 上传手机拍摄的书法图片
- 软件自动检测行列切割线
- 可手动拖动切割线调整位置，Shift+双击添加新切割线

### ③ 切割调整（预处理工具）

- 逐字检查切割结果
- 删除噪点、错字、空白切片

### ④ 缩放校正（预处理工具）

- 统一字符像素尺寸
- 自动居中排版

### ⑤ 标注出图（预处理工具）

- 三种标注模式可选：
  - **繁简混合**
  - **以简为主**
  - **以繁为主**
- 支持批量标注和手动逐字标注
- 导出后自动清理中间文件
- 命名规范：BMP 字符 `uniXXXX`，扩展区字符 `uXXXXX`

### ⑥ PNG → TTF（FontLab / FontForge / fontTools）

把第 ⑤ 步导出的字符 PNG 合成字体文件：

- **FontLab / FontForge**：GUI 操作，导入 PNG + 设置度量 + 导出 TTF
- **fontTools**：Python 脚本化（适合批量或 CI 流）
- 命名格式建议遵循 FontLab 标准（`uni4E00` / `u20000` 等）

### ⑦ AI 补全生僻字（本项目）

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

**最简入手：** 从 https://github.com/gaudi1209/gaudi-font-preprocess/releases 下载独立运行版 zip，解压后双击 `启动.bat` 即可使用，无需安装 Python 及任何依赖。

**从源码运行：**

```bash
git clone https://github.com/gaudi1209/gaudi-font-preprocess.git
cd gaudi-font-preprocess
pip install -r requirements.txt
python app.py
# 访问 http://localhost:7500
```

本项目（7550）的启动方式见 [README.md](../README.md) 与项目根目录的 `AI字库启动7550.bat`。