# Xwork · 插件市场

这是「Xwork」的**在线插件市场**数据仓库，通过 GitHub 托管分发。

Xwork 程序从本仓库拉取插件索引并下载插件包，无需自建服务器。

## 目录结构

```
.
├── market/
│   └── index.json              # 市场索引（唯一入口，程序从这里开始读）
└── plugins/
    └── <插件id>/
        └── <插件id>-<版本>.zip  # 插件发布包（含 manifest.json + backend.py + 页面资源）
```

## 索引格式（market/index.json）

```json
{
  "generated_by": "xwork",
  "plugins": [
    {
      "id": "xwork.page-demo",          // 唯一，须与插件 manifest.json 的 id 一致
      "name": "页面示例",                // 展示名
      "version": "1.0.0",               // 语义化版本
      "description": "...",             // 描述（市场列表与详情页展示）
      "category": "示例",               // 分类（市场页按此分组/筛选）
      "author": "xwork",      // 可选，作者
      "homepage": "",                   // 可选，主页
      "permissions": ["fs.read"],       // 请求的权限（仅展示；真实授权仍在本机单独确认）
      "min_app": "0.0.1",               // 可选，最低主程序版本
      "download": "plugins/xwork.page-demo/xwork.page-demo-1.0.0.zip",  // 相对本仓库根
      "sha256": "c569...",              // zip 文件的 SHA-256（安装时强校验）
      "size": 4969                      // 可选，zip 字节数
    }
  ]
}
```

**硬性字段**：`id` / `name` / `version` / `download` / `sha256`。缺任何一个，程序会跳过该条目。

### 两条版本线不要混

| 字段 | 属于 | 当前值 | 说明 |
|---|---|---|---|
| `version`（索引与 manifest 内） | **插件自己的版本** | `1.1.0` | 独立演进，与主程序版本无关；改了就要重打包并重算 `sha256` |
| `min_app` / `engines.xwork` | **主程序版本要求** | `0.0.1` | 必须与 Xwork 当前版本对齐。主程序版本一变，这里要跟着改，否则插件会因 `engines` 硬校验被拒绝加载 |

> 主程序当前版本：**0.0.1**。`engines.xwork` 是硬校验（不满足直接拒绝加载），
> `min_app` 只做展示（市场页「需 vX+」标记），两者要一起改。

## 发布 / 更新流程

1. **开发插件**：按 manifest 规范写 `manifest.json` + `backend.py` + 可选页面资源。
2. **打包 zip**：把插件目录打成 `<id>-<version>.zip`（zip 根下直接是 manifest.json，或单层目录）。
3. **算 sha256**：`sha256sum <id>-<version>.zip`。
4. **放包**：zip 放到 `plugins/<id>/`。
5. **登记索引**：在 `market/index.json` 的 `plugins` 数组里加/更新一条，填对 `download`、`sha256`、`version`。
6. **提交**：commit + push，程序拉索引即能发现。

## 客户端行为

- 拉取 `market/index.json`（多镜像降级：raw 直连 → ghproxy）。
- 安装：下载 zip → 校验 sha256 → 解压校验 manifest → 落到 `plugins/<id>/`，**默认禁用**，用户手动启用并授权。
- 更新：比对 `version`，有新版可点「更新」，先备份旧目录再原子替换，失败回滚。
- 卸载：删目录 + 清授权与自配置。

## 安全约定

- 插件与主程序**同进程**运行，请只发布/安装信任的插件。
- 索引里的 `permissions` 只是声明展示；本机启用时仍会逐个权限让用户勾选确认，高危权限（如 `system.exec`）默认拒绝。
- zip 必须能通过 sha256 校验，杜绝篡改与断链。
