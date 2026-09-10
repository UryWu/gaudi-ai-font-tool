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

---

## 补丁 2：best checkpoint（loss 最小）保存

**文件：**
- `<ENGINE_DIR>/engine_jit.py` — `train_one_epoch`
- `<ENGINE_DIR>/lora_finetune_jit.py` — 训练主循环 + 辅助函数

**问题：** 引擎原本只保存 `checkpoint-last.pth`（最新一轮），不保存 loss 最小的模型。
`train_one_epoch` 也不返回本轮 loss，上层无法比较。

**修复：**

1) `engine_jit.py` 的 `train_one_epoch` 末尾返回本轮平均 loss：

```diff
                 log_writer.add_scalar('train_loss', loss_value_reduce, epoch_1000x)
                 log_writer.add_scalar('lr', lr, epoch_1000x)
+
+    # [本地补丁] 返回本轮平均 loss，供上层挑选 best checkpoint
+    try:
+        return float(metric_logger.meters['loss'].global_avg)
+    except Exception:
+        return None
```

2) `lora_finetune_jit.py` 训练主循环比较并保存：

```diff
     print(f"Start LoRA training for {args.epochs} epochs")
     start_time = time.time()
+
+    # [本地补丁] 初始化 best_loss：优先读持久化文件，否则从历史日志恢复
+    best_loss = _read_best_loss(args.output_dir)
+    if best_loss is None:
+        best_loss = _seed_best_loss_from_logs(args.output_dir)
     for epoch in range(args.start_epoch, args.epochs):
         ...
-        train_one_epoch(model, model_without_ddp, data_loader_train, optimizer, device, epoch, log_writer=log_writer,
-                        args=args)
+        epoch_loss = train_one_epoch(model, model_without_ddp, data_loader_train, optimizer, device, epoch,
+                                     log_writer=log_writer, args=args)
+
+        # [本地补丁] loss 更小则保存 checkpoint-best.pth
+        if epoch_loss is not None and misc.is_main_process():
+            if best_loss is None or epoch_loss < best_loss:
+                best_loss = epoch_loss
+                save_model_no_ema(args=args, model_without_ddp=model_without_ddp, epoch=epoch, epoch_name="best")
+                _write_best_loss(args.output_dir, best_loss)
```

3) 新增辅助函数（同文件模块级）：`_best_loss_path` / `_read_best_loss` /
`_write_best_loss` / `_seed_best_loss_from_logs`。

**关键设计——best 跨续训持久化：**
- best loss 存 `<批次>/.logs/best_loss.txt`
- 续训时先读该文件；**若不存在**（例如首次启用本补丁），则
  `_seed_best_loss_from_logs` 解析历史 `train_*.log`，按 epoch 取轮末平均 loss 的最小值，
  并**立即写入 `best_loss.txt`**（避免下次再依赖日志；日志被清理也不丢历史基准）
- 这样**续训首轮即使变差，也不会被误当作 best 覆盖**

**验证（两种分支均已实测）：**
- 历史最小 loss = 0.2355，续训 1 轮得 0.2886 →
  `[best] epoch 11 loss=0.2886 >= best 0.2355 → 不更新`，未生成 `checkpoint-best.pth` ✅
- 手工把 `best_loss.txt` 设为 999 后续训 1 轮（loss 0.28 < 999）→
  生成 `checkpoint-best.pth`，`best_loss.txt` 更新为 0.28 ✅
