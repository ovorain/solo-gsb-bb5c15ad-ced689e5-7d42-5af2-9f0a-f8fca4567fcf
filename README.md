# JSON Three-Way Merge Service

一个基于 FastAPI 的 JSON 三方合并与 JSON Patch 服务：

- `POST /merge` 接收 `base`、`left`、`right` 三个 JSON 文档，将 left 和 right
  各自相对 base 的修改合并后返回；存在冲突时返回 `409` 并按 JSON Pointer 列出
  全部冲突。
- `POST /patch` 接收 `document` 与 `operations`，按 RFC 6902 在深拷贝上原子地
  依次执行 `add` / `remove` / `replace` / `test`，全部成功才返回结果。

## 快速开始

一条命令启动（依赖随镜像构建自动安装）：

```bash
docker compose up --build
```

服务地址：http://localhost:8000 （交互式文档：http://localhost:8000/docs）

本地开发（不用 Docker）：

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## API

### `POST /merge`

请求体为三个任意 JSON 值（对象、数组、标量均可）：

```json
{
  "base":  { "a": 1, "b": [1, 2] },
  "left":  { "a": 2, "b": [1, 2] },
  "right": { "a": 1, "b": [1, 2, 3] }
}
```

**合并成功 → `200`**，返回合并结果：

```json
{ "merged": { "a": 2, "b": [1, 2, 3] } }
```

**合并冲突 → `409`**，返回按 JSON Pointer（RFC 6901）排序的冲突列表：

```json
{
  "detail": "merge conflict",
  "conflicts": [
    {
      "path": "/a",
      "base":  { "present": true,  "value": 1 },
      "left":  { "present": false, "value": null },
      "right": { "present": true,  "value": 2 }
    }
  ]
}
```

每个冲突包含：

| 字段    | 说明                                                         |
| ------- | ------------------------------------------------------------ |
| `path`  | 冲突位置的 JSON Pointer（根冲突为空字符串 `""`）             |
| `base`  | base 在该路径的值                                            |
| `left`  | left 在该路径的值                                            |
| `right` | right 在该路径的值                                           |

每一侧用 `{"present": bool, "value": ...}` 表示，以此**区分键缺失与 null**：
键不存在时 `present: false`（`value` 固定为 `null`）；键存在且值为 JSON `null`
时 `present: true, value: null`。

### `POST /patch`

按 RFC 6902 对 `document` 应用一组补丁操作。请求体：

```json
{
  "document": { "a": [1, 2], "b": { "c/d": 1 } },
  "operations": [
    { "op": "add",     "path": "/a/-",    "value": 3 },
    { "op": "test",    "path": "/b/c~1d", "value": 1 },
    { "op": "replace", "path": "/b",      "value": null }
  ]
}
```

**全部成功 → `200`**，返回最终文档：

```json
{ "document": { "a": [1, 2, 3], "b": null } }
```

**操作失败 → `409`**，返回失败操作的信息，且不返回任何部分结果：

```json
{
  "detail": "patch failed",
  "failed_index": 1,
  "path": "/a/9",
  "reason": "array index 9 out of bounds (length 3)"
}
```

**请求结构非法 → `422`**：操作不是对象、`op` 未知或缺失、`path` 缺失或不是
合法的 JSON Pointer（如未以 `/` 开头、`~` 后未跟 `0`/`1`）、`add`/`replace`/
`test` 缺少 `value`、`remove` 携带了 `value`，以及 `document`/`operations`
字段缺失等。

补丁规则：

1. **原子性**：操作按数组顺序在深拷贝上依次执行；任一操作失败则整体失败，
   原 `document` 不受影响，响应中不含部分结果。
2. **JSON Pointer**（RFC 6901）：`~0` 表示 `~`，`~1` 表示 `/`；空字符串 `""`
   指向整个文档（根路径）。
3. **`add`**：对象键不存在则新增、存在则替换；数组按索引插入，索引等于数组
   长度或用 `-` 表示追加到末尾；不会自动创建中间路径。
4. **`remove` / `replace` / `test`**：目标必须已存在，且不得使用 `-`；否则
   返回 `409`。
5. **`test`**：用与 `/merge` 相同的 JSON 相等性规则比较（`1` 等于 `1.0`，
   但 `true` 不等于 `1`），不相等返回 `409`。
6. **`add` / `replace` / `test` 必须携带 `value`（`null` 也是合法值），
   `remove` 禁止携带 `value`**，违反返回 `422`。

### `GET /health`

健康检查，返回 `{"status": "ok"}`。

## 合并规则

1. **两侧相同**（包括都未修改、都删除、做了相同修改）→ 取该值。
2. **仅一侧修改** → 取修改后的值（删除即移除该键）。
3. **两侧修改不同**：
   - 三者（或两侧新增时）都是对象 → 按键递归合并；
   - 否则（同路径异值、类型变化、数组两侧改得不同）→ 冲突，返回 `409`。
4. **一侧删除、另一侧修改其内部后代** → 冲突，返回 `409`。
5. **数组整体比较**：不做逐元素合并；仅一侧改了数组则取该侧，两侧改成不同
   数组则整个数组作为一个冲突上报。

## 示例

```bash
# 合并成功
curl -s -X POST http://localhost:8000/merge \
  -H 'Content-Type: application/json' \
  -d '{"base":{"a":1},"left":{"a":2},"right":{"a":1}}'
# => {"merged":{"a":2}}

# 冲突：left 删除了 /a，right 修改了 /a 的后代
curl -s -X POST http://localhost:8000/merge \
  -H 'Content-Type: application/json' \
  -d '{"base":{"a":{"x":1}},"left":{},"right":{"a":{"x":2}}}'
# => 409 {"detail":"merge conflict","conflicts":[{"path":"/a", ...}]}

# 打补丁：数组追加 + 测试 + 替换
curl -s -X POST http://localhost:8000/patch \
  -H 'Content-Type: application/json' \
  -d '{"document":{"a":[1,2]},"operations":[{"op":"add","path":"/a/-","value":3},{"op":"test","path":"/a/0","value":1}]}'
# => {"document":{"a":[1,2,3]}}

# 补丁失败：第二个操作越界，整体不生效
curl -s -X POST http://localhost:8000/patch \
  -H 'Content-Type: application/json' \
  -d '{"document":{"a":[1]},"operations":[{"op":"add","path":"/a/-","value":2},{"op":"remove","path":"/a/9"}]}'
# => 409 {"detail":"patch failed","failed_index":1,"path":"/a/9","reason":"array index 9 out of bounds (length 2)"}
```

## 测试

```bash
pip install -r requirements-dev.txt
pytest
```

## 项目结构

```
app/main.py          # FastAPI 应用与三方合并算法
app/patch.py         # RFC 6902 JSON Patch（指针解析与原子执行）
app/jsonutil.py      # 共享的 JSON 相等性与指针转义
tests/test_merge.py  # /merge 的 pytest 测试
tests/test_patch.py  # /patch 的 pytest 测试
requirements.txt     # 运行依赖（Docker 构建时自动安装）
requirements-dev.txt # 测试依赖
Dockerfile
docker-compose.yml
```
