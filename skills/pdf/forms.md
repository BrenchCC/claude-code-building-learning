**重要提示：您必须按顺序完成这些步骤。不要提前跳过编写代码。**

如果您需要填写 PDF 表单，请首先检查 PDF 是否有可填写的表单字段。从该文件所在目录运行此脚本：
`python scripts/check_fillable_fields <file.pdf>`，根据结果转到"可填写字段"或"不可填写字段"部分并遵循相应说明。

# 可填写字段

如果 PDF 有可填写的表单字段：
- 从该文件所在目录运行此脚本：`python scripts/extract_form_field_info.py <input.pdf> <field_info.json>`。它将创建一个包含字段列表的 JSON 文件，格式如下：
```
[
  {
    "field_id": (字段的唯一 ID),
    "page": (页码，从 1 开始),
    "rect": ([左, 下, 右, 上] 边界框，PDF 坐标，y=0 在页面底部),
    "type": ("text", "checkbox", "radio_group", 或 "choice"),
  },
  // 复选框具有 "checked_value" 和 "unchecked_value" 属性：
  {
    "field_id": (字段的唯一 ID),
    "page": (页码，从 1 开始),
    "type": "checkbox",
    "checked_value": (设置此字段为此值以选中复选框),
    "unchecked_value": (设置此字段为此值以取消选中复选框),
  },
  // 单选按钮组具有包含可能选项的 "radio_options" 列表。
  {
    "field_id": (字段的唯一 ID),
    "page": (页码，从 1 开始),
    "type": "radio_group",
    "radio_options": [
      {
        "value": (设置此字段为此值以选择此单选按钮选项),
        "rect": (此选项的单选按钮的边界框)
      },
      // 其他单选按钮选项
    ]
  },
  // 多选字段具有包含可能选项的 "choice_options" 列表：
  {
    "field_id": (字段的唯一 ID),
    "page": (页码，从 1 开始),
    "type": "choice",
    "choice_options": [
      {
        "value": (设置此字段为此值以选择此选项),
        "text": (选项的显示文本)
      },
      // 其他选项
    ],
  }
]
```
- 使用此脚本将 PDF 转换为 PNG 图片（每页一张图片）（从该文件所在目录运行）：
`python scripts/convert_pdf_to_images.py <file.pdf> <output_directory>`
然后分析图片以确定每个表单字段的用途（确保将边界框 PDF 坐标转换为图片坐标）。
- 创建一个 `field_values.json` 文件，格式如下，包含要为每个字段输入的值：
```
[
  {
    "field_id": "last_name", // 必须与 extract_form_field_info.py 中的 field_id 匹配
    "description": "用户的姓氏",
    "page": 1, // 必须与 field_info.json 中的 "page" 值匹配
    "value": "Simpson"
  },
  {
    "field_id": "Checkbox12",
    "description": "如果用户年满 18 岁则选中此复选框",
    "page": 1,
    "value": "/On" // 如果是复选框，请使用其 "checked_value" 值来选中它。如果是单选按钮组，请使用 "radio_options" 中的一个 "value" 值。
  },
  // 更多字段
]
```
- 从该文件所在目录运行 `fill_fillable_fields.py` 脚本来创建填写后的 PDF：
`python scripts/fill_fillable_fields.py <输入 PDF> <field_values.json> <输出 PDF>`
此脚本将验证您提供的字段 ID 和值是否有效；如果打印错误消息，请更正相应字段并再次尝试。

# 不可填写字段

如果 PDF 没有可填写的表单字段，您需要直观地确定应在何处添加数据并创建文本注释。**必须完全按照以下步骤执行。您必须执行所有这些步骤以确保表单准确填写。** 每个步骤的详细信息如下。
- 将 PDF 转换为 PNG 图片并确定字段边界框。
- 创建包含字段信息和显示边界框的验证图像的 JSON 文件。
- 验证边界框。
- 使用边界框填写表单。

## 步骤 1：视觉分析（必需）
- 将 PDF 转换为 PNG 图片。从该文件所在目录运行此脚本：
`python scripts/convert_pdf_to_images.py <file.pdf> <output_directory>`
该脚本将为 PDF 中的每一页创建一张 PNG 图片。
- 仔细检查每张 PNG 图片，识别所有表单字段和用户应输入数据的区域。对于用户应输入文本的每个表单字段，确定表单字段标签和用户应输入文本的区域的边界框。标签和输入边界框**不得相交**；文本输入框应仅包含应输入数据的区域。该区域通常会紧邻其标签的一侧、上方或下方。输入边界框的高度和宽度必须足够包含其文本。

以下是您可能看到的一些表单结构示例：

*框内标签*
```
┌────────────────────────┐
│ 姓名：                  │
└────────────────────────┘
```
输入区域应在"姓名"标签的右侧，并延伸到框的边缘。

*行前标签*
```
邮箱：_______________________
```
输入区域应在线上方并包含其整个宽度。

*线下标签*
```
_________________________
姓名
```
输入区域应在线上方并包含线的整个宽度。这在签名和日期字段中很常见。

*线上标签*
```
请输入任何特殊要求：
________________________________________________
```
输入区域应从标签底部延伸到线条，并包含线条的整个宽度。

*复选框*
```
您是美国公民吗？ 是 □  否 □
```
对于复选框：
- 寻找小方形框（□）——这些是要定位的实际复选框。它们可能在其标签的左侧或右侧。
- 区分标签文本（"是"、"否"）和可点击的复选框方形。
- 输入边界框应**仅**覆盖小方形，而不是文本标签。

## 步骤 2：创建 fields.json 和验证图像（必需）
- 创建一个名为 `fields.json` 的文件，包含表单字段信息和边界框，格式如下：
```
{
  "pages": [
    {
      "page_number": 1,
      "image_width": (第一页图片宽度，单位为像素),
      "image_height": (第一页图片高度，单位为像素),
    },
    {
      "page_number": 2,
      "image_width": (第二页图片宽度，单位为像素),
      "image_height": (第二页图片高度，单位为像素),
    }
    // 更多页面
  ],
  "form_fields": [
    // 文本字段示例。
    {
      "page_number": 1,
      "description": "用户的姓氏应在此处输入",
      // 边界框格式为 [左, 上, 右, 下]。标签和文本输入的边界框不应重叠。
      "field_label": "姓氏",
      "label_bounding_box": [30, 125, 95, 142],
      "entry_bounding_box": [100, 125, 280, 142],
      "entry_text": {
        "text": "Johnson", // 此文本将作为注释添加到 entry_bounding_box 位置
        "font_size": 14, // 可选，默认为 14
        "font_color": "000000", // 可选，RRGGBB 格式，默认为 000000（黑色）
      }
    },
    // 复选框示例。定位方形作为输入边界框，而不是文本。
    {
      "page_number": 2,
      "description": "如果用户年满 18 岁，则应选中此复选框",
      "entry_bounding_box": [140, 525, 155, 540],  // 复选框方形上方的小框
      "field_label": "是",
      "label_bounding_box": [100, 525, 132, 540],  // 包含"是"文本的框
      // 使用"X"表示选中复选框。
      "entry_text": {
        "text": "X",
      }
    }
    // 更多表单字段条目
  ]
}
```

通过从该文件所在目录为每一页运行此脚本来创建验证图像：
`python scripts/create_validation_image.py <page_number> <path_to_fields.json> <input_image_path> <output_image_path>`

验证图像将在应输入文本的位置显示红色矩形，并在标签文本上显示蓝色矩形。

## 步骤 3：验证边界框（必需）
### 自动交叉检查
- 使用 `check_bounding_boxes.py` 脚本（从该文件所在目录运行）检查 fields.json 文件，以验证没有边界框相交以及输入边界框是否足够高：
`python scripts/check_bounding_boxes.py <JSON 文件>`

如果有错误，请重新分析相关字段，调整边界框，并反复迭代直到没有剩余错误。记住：标签（蓝色）边界框应包含文本标签，输入（红色）框不应包含。

### 手动图像检查
**重要提示：在未视觉检查验证图像之前，请勿继续**
- 红色矩形必须**仅**覆盖输入区域
- 红色矩形**不得**包含任何文本
- 蓝色矩形应包含标签文本
- 对于复选框：
  - 红色矩形必须居中于复选框方形上
  - 蓝色矩形应覆盖复选框的文本标签

- 如果任何矩形看起来不正确，请修复 fields.json，重新生成验证图像，并再次验证。重复此过程直到边界框完全准确。


## 步骤 4：向 PDF 添加注释
从该文件所在目录运行此脚本，使用 fields.json 中的信息创建填写后的 PDF：
`python scripts/fill_pdf_form_with_annotations.py <输入 PDF 路径> <path_to_fields.json> <输出 PDF 路径>`
