# zi2zi-JiT 引擎本地补丁记录

引擎源码不在本仓库内（clone 在 `G:\Projects\projects_ai\zi2zi-JiT`）。
若重新 clone 引擎，需要重新应用下面的补丁。

---

## 补丁 1：字体目录识别加白名单（`main_jit.py`）

**文件：** `<ENGINE_DIR>/main_jit.py`，`FontSrcTargetRefsDataset.__init__`

**问题：** 引擎把 `data_path` 下**所有非 `.` 开头的子目录**都当「字体目录」，
并按 `<数字>_xxx` 规则解析 font_idx（`int(font.split('_')[0]) - 1`）。
批次目录里只要有其它子目录（如生字产物 `gen_<ts>/`、测试产物 `_test_quick_output/`），
就会 `ValueError: invalid literal for int() with base 10: 'gen'` 导致训练/续训崩溃。

**修复：** 只接受形如 `001_font` 的目录（`^'?\d+_`），其余跳过。

```diff
-        font_dirs = sorted([
-            d for d in os.listdir(root)
-            if os.path.isdir(os.path.join(root, d)) and not d.startswith('.')
-        ])
+        # [本地补丁] 只认形如 <数字>_xxx 的字体目录（如 001_font），
+        # 跳过 gen_*/_test_* 等批次目录内的其它子目录，避免 int('gen') 崩溃
+        import re as _re
+        font_dirs = sorted([
+            d for d in os.listdir(root)
+            if os.path.isdir(os.path.join(root, d))
+            and not d.startswith('.')
+            and _re.match(r"^'?\d+_", d)
+        ])
```

**为什么需要：** 本项目约定「生字产物 `gen_<ts>/` 嵌套在训练批次目录下」（见
[scripts-guide.md](scripts-guide.md) 目录布局），该子目录会被引擎误当字体目录。

**验证：** 补丁后从 `train_images_20260910_160142/checkpoint-last.pth`（epoch=9）
续训 `continueEpochs=1` → 引擎正常从 epoch 10 训 1 轮，产出 epoch=10 的 checkpoint。
