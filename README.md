# JSON Merge & Patch Service

一个基于 FastAPI 的 JSON 处理服务，提供两个接口：

- `POST /merge`：接收 `base`、`left`、`right` 三个 JSON 文档，将 left 和 right
  各自相对 base 的修改做三方合并；存在冲突时返回 `409` 并按 JSON Pointer 列出
  全部冲突。
- `POST /patch`：接收 `document` 与 `operations`，按数组顺序在**深拷贝**上原子
  执行 [RFC 6902](https://www.rfc-editor.org/rfc/rfc6902) JSON Patch 的
  `add`、`remove`、`replace`、`test` 操作。

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

请求体：

| 字段         | 类型    | 说明                                   |
| ------------ | ------- | -------------------------------------- |
| `document`   | 任意 JSON | 待打补丁的文档                        |
| `operations` | 数组    | 按顺序执行的 RFC 6902 操作             |

```json
{
  "document": { "a": [1, 2], "b": 3 },
  "operations": [
    { "op": "test",    "path": "/b",     "value": 3 },
    { "op": "add",     "path": "/a/-",   "value": 3 },
    { "op": "replace", "path": "/b",     "value": 30 },
    { "op": "add",     "path": "/c",     "value": "new" }
  ]
}
```

**全部成功 → `200`**，返回最终文档：

```json
{ "document": { "a": [1, 2, 3], "b": 30, "c": "new" } }
```

操作在 `document` 的**深拷贝**上执行，原请求文档不会被修改；失败时也绝不返回
部分结果。

#### 操作语义

| op        | `value` | 语义                                                         |
| --------- | ------- | ------------------------------------------------------------ |
| `add`     | 必须    | 对象：新增键，键已存在则等价于 `replace`；数组：在索引前插入，末级 token 为 `-` 时追加；根路径：替换整个文档 |
| `remove`  | 禁止    | 删除对象键或数组元素（数组后续元素前移）；不得指向根路径     |
| `replace` | 必须    | 替换**已存在**的目标；根路径替换整个文档                     |
| `test`    | 必须    | 断言目标值与 `value` JSON 相等，不等则失败                   |

- `add` 的数组索引允许等于当前长度（效果同追加）；`replace`/`remove`/`test`
  的目标必须已存在，索引必须在 `[0, length)` 内。
- 只有 `add` 可以使用 `-`（追加标记），其他操作携带 `-` 一律视为请求非法。
- `test` 的相等性沿用合并接口的规则：`1` 与 `1.0` 相等，`true` 与 `1` 不等，
  数组/对象递归比较。

**路径不存在、数组越界或 test 失败 → `409`**：

```json
{
  "detail": "patch conflict",
  "failed_index": 2,
  "path": "/b",
  "reason": "test failed: target value differs from 'value'"
}
```

| 字段           | 说明                                           |
| -------------- | ---------------------------------------------- |
| `failed_index` | 失败操作在 `operations` 中的下标（从 0 开始） |
| `path`         | 失败操作的 JSON Pointer                        |
| `reason`       | 失败原因                                       |

**指针语法或操作结构非法 → `422`**（同样带 `failed_index` / `path` /
`reason`；错误在任何操作执行前检出）：

- 缺少 `op` / `path`，或 `op` 不在支持列表内；
- `add`/`replace`/`test` 缺少 `value`，或 `remove` 携带 `value`；
- JSON Pointer 非空且不以 `/` 开头、`~` 后不是 `0`/`1`；
- 数组位置的 token 不是数字、带前导零（`/01`），或非 `add` 操作使用 `-`。

```json
{
  "detail": "invalid patch operation",
  "reason": "'remove' must not carry a 'value' field",
  "failed_index": 1,
  "path": "/a"
}
```

#### JSON Pointer 转义

路径按 RFC 6901 以 `/` 分隔；键名中的特殊字符用 `~1` 表示 `/`、`~0` 表示
`~`（先解 `~1` 再解 `~0`）。空字符串 `""` 指向整个文档。例如键 `a/b`写作
`/a~1b`，键 `~x` 写作 `/~0x`。

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

# JSON Patch：数组追加 + 断言 + 替换
curl -s -X POST http://localhost:8000/patch \
  -H 'Content-Type: application/json' \
  -d '{"document":{"a":[1],"b":3},"operations":[{"op":"add","path":"/a/-","value":2},{"op":"test","path":"/b","value":3}]}'
# => {"document":{"a":[1,2],"b":3}}

# test 失败 → 409（无部分结果）
curl -s -X POST http://localhost:8000/patch \
  -H 'Content-Type: application/json' \
  -d '{"document":{"a":1},"operations":[{"op":"add","path":"/b","value":2},{"op":"test","path":"/a","value":99}]}'
# => 409 {"detail":"patch conflict","failed_index":1,"path":"/a","reason":"test failed: ..."}
```

## 测试

```bash
pip install -r requirements-dev.txt
pytest
```

## 项目结构

```
app/main.py          # FastAPI 应用：/merge 三方合并与 /patch 入口
app/patch.py         # RFC 6902 JSON Patch 校验与原子执行
app/jsonutil.py      # JSON 相等性与 MISSING 哨兵（两个接口共用）
tests/test_merge.py  # /merge 测试
tests/test_patch.py  # /patch 测试
requirements.txt     # 运行依赖（Docker 构建时自动安装）
requirements-dev.txt # 测试依赖
Dockerfile
docker-compose.yml
```
