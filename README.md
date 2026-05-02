# 云雾AI 图像生成工具

基于云雾API (https://yunwu.ai) 的 Windows GUI 图像生成工具。

## 功能特性

- **文字生图**: 纯 Prompt 调用 generations 接口
- **参考图生图**: 上传 1-6 张参考图，调用 edits 接口
- **参考图管理**: 缩略图展示，可逐张删除，支持拖拽添加
- **配置选项**: model / size / quality / n 全部支持
- **结果预览**: 可滚动图片网格，点击放大查看
- **保存功能**: 单张保存 / 批量保存，自动时间戳命名

## 快速运行

```bash
pip install -r requirements.txt
python main.py
```

## 打包为 exe

Windows:
```
build.bat
```

Linux:
```
bash build.sh
```

## 依赖

- requests
- Pillow
- tkinterdnd2 (可选，支持拖拽)
- PyInstaller (打包时需要)
