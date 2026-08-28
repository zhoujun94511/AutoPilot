# 关键字核实矩阵

> bucket: pure=离线白盒可直调 / device=需真机或浏览器 / service=需外部服务；tested=该 id 在 tests/ 中出现过（粗覆盖信号）

# iOS WDA-direct 真机签字（Win，2026-07；用例 TEST002 端到端通过）

| 关键字                                     | WDA-direct | 备注                       |
|-----------------------------------------|------------|--------------------------|
| `appium_start`                          | ✅          | 自动跳过                     |
| `mobile_app_install_and_open`           | ✅          | pymobiledevice3 装 IPA    |
| `elementClick`                          | ✅          | Alert API + 弱 hint       |
| `mobile_element_click`                  | ✅          | predicate/xpath          |
| `mobile_swipe_direction`                | ✅          | scrollview/xctest/w3c 分层 |
| `mobile_app_adb_uninstall`              | ✅          | iOS 卸载                   |
| `mobile_app_start` / `mobile_app_close` | ✅          | 会话生命周期                   |

> 完整 320 项矩阵见下文；上表为 iOS WDA 主干真机签字子集。

## 概览

```
关键字总计 ~333（含 API 增强增量；历史基线 320）
  pure / device / service 分布见明细表
  Http API 增强（2026-07）：session/auth/assert/env + patch/head/options
  覆盖信号：tests/test_http_session.py（Session/Auth/Assert/Env）
```

> 完整矩阵见下文。API 导入桥（OpenAPI/Postman→.tc.yaml）**缓做**，见 `docs/architecture/API_TESTING_PLAN.md`。

## 明细

| bucket  | 类目     | 模块                          | id                                     | 名称                          | 已测 |
|---------|--------|-----------------------------|----------------------------------------|-----------------------------|----|
| device  | Mobile | mobile.element              | `Shelter`                              | 智能防键盘遮挡                     | —  |
| device  | Mobile | mobile.element              | `mobile_activity_switch`               | Activity来回切换(mobile)        | —  |
| device  | Mobile | mobile.element              | `mobile_any_element_click`             | 点击任意位置控件(wap)               | —  |
| device  | Mobile | mobile.element              | `mobile_element_JS_click`              | 控件JS点击(wap)                 | —  |
| device  | Mobile | mobile.element              | `mobile_element_adb_input_text`        | adb命令文本框文本输入(mobile)        | —  |
| device  | Mobile | mobile.element              | `mobile_element_check_select`          | 多选框点击(mobile)               | —  |
| device  | Mobile | mobile.element              | `mobile_element_click`                 | 点击元素                        | ✅  |
| device  | Mobile | mobile.element              | `mobile_element_combo_select`          | 下拉列表选择(mobile)              | —  |
| device  | Mobile | mobile.element              | `mobile_element_continuous_click`      | 控件连续点击(mobile)              | —  |
| device  | Mobile | mobile.element              | `mobile_element_get_element_attribute` | 获取控件属性(mobile/wap)          | —  |
| device  | Mobile | mobile.element              | `mobile_element_get_element_enabled`   | 获取控件可用性(mobile/wap)         | —  |
| device  | Mobile | mobile.element              | `mobile_element_get_element_exist`     | 判断元素存在                      | ✅  |
| device  | Mobile | mobile.element              | `mobile_element_get_element_text`      | 获取元素文本                      | ✅  |
| device  | Mobile | mobile.element              | `mobile_element_get_element_visible`   | 获取控件可见性(mobile/wap)         | ✅  |
| device  | Mobile | mobile.element              | `mobile_element_radio_click`           | 单选框点击(mobile)               | —  |
| device  | Mobile | mobile.element              | `mobile_element_shift_click`           | [公用]控件点击+偏移量(mobile)        | —  |
| device  | Mobile | mobile.element              | `mobile_element_swipe`                 | 滑动元素                        | ✅  |
| device  | Mobile | mobile.element              | `mobile_element_text_clear`            | 清除文本                        | ✅  |
| device  | Mobile | mobile.element              | `mobile_element_text_input`            | 输入文本                        | ✅  |
| device  | Mobile | mobile.element              | `mobile_element_text_input_adb`        | adb输入法文本框文本输入(mobile/wap)   | —  |
| device  | Mobile | mobile.element              | `swipe_login`                          | 滑动登录（若存在）                   | —  |
| device  | Mobile | mobile.misc                 | `backToTab`                            | 回到tab栏展示                    | —  |
| device  | Mobile | mobile.misc                 | `elementClick`                         | 判断并控件点击(mobile/wap)         | —  |
| device  | Mobile | mobile.misc                 | `mobileProduct_app_getPrice`           | 获取price                     | —  |
| device  | Mobile | mobile.misc                 | `mobile_SDK_ergodic`                   | SDK按钮遍历                     | ✅  |
| device  | Mobile | mobile.misc                 | `mobile_browser_wait_for_exist`        | [公用]等待控件存在性判断(mobile)       | —  |
| device  | Mobile | mobile.misc                 | `mobile_browser_wait_for_text`         | [公用]等待控件文本匹配性判断(mobile)     | —  |
| device  | Mobile | mobile.misc                 | `mobile_get_current_activity`          | 获取当前Activity                | —  |
| device  | Mobile | mobile.misc                 | `mobile_get_deviceinfo`                | 获取设备参数信息                    | ✅  |
| device  | Mobile | mobile.misc                 | `mobile_monkey`                        | 执行Monkey稳定性测试               | —  |
| device  | Mobile | mobile.misc                 | `mobile_pull_file_to_mobile`           | push文件                      | —  |
| device  | Mobile | mobile.misc                 | `mobile_start_activity`                | 启动Activity                  | —  |
| device  | Mobile | mobile.misc                 | `mobile_toast_verify`                  | android端toast消息验证           | —  |
| device  | Mobile | mobile.misc                 | `mobile_verify_element_attribute`      | [公用]校验控件属性值(mobile)         | —  |
| device  | Mobile | mobile.misc                 | `mobile_verify_element_enabled`        | [公用]校验控件是否可用(mobile)        | —  |
| device  | Mobile | mobile.misc                 | `mobile_verify_element_existed`        | [公用]校验控件是否存在(mobile)        | —  |
| device  | Mobile | mobile.misc                 | `mobile_verify_element_text`           | [公用]校验控件文本(mobile)          | —  |
| device  | Mobile | mobile.misc                 | `mobile_verify_element_visible`        | [公用]校验控件是否可见(mobile)        | —  |
| device  | Mobile | mobile.misc                 | `mobile_wait_element_enabled`          | [公用]等待控件可用性判断(mobile)       | —  |
| device  | Mobile | mobile.misc                 | `mobile_wait_element_visible`          | [公用]等待控件可见性判断(mobile)       | —  |
| device  | Mobile | mobile.misc                 | `textInput`                            | 判断并文本框输入文本(mobile/wap)      | ✅  |
| device  | Mobile | mobile.session              | `appium_start`                         | 启动appium服务                  | ✅  |
| device  | Mobile | mobile.session              | `appium_stop`                          | 停止appium服务                  | —  |
| device  | Mobile | mobile.session              | `boolean_app_isInstalled`              | 获取应用是否已经安装(mobile)          | —  |
| device  | Mobile | mobile.session              | `installAdbkeyboard`                   | 安装adbkeyboard输入法            | —  |
| device  | Mobile | mobile.session              | `installUtf7Ime`                       | 安装中文输入法                     | —  |
| device  | Mobile | mobile.session              | `intentToMiniProgram`                  | 通过URL Scheme跳转到小程序          | —  |
| device  | Mobile | mobile.session              | `mobile_app_adb_uninstall`             | 卸载移动应用                      | —  |
| device  | Mobile | mobile.session              | `mobile_app_close`                     | 关闭App                       | ✅  |
| device  | Mobile | mobile.session              | `mobile_app_get_package_and_activity`  | 获取app包名和入口Activity          | ✅  |
| device  | Mobile | mobile.session              | `mobile_app_install_and_open`          | [公用]安装并启动被测应用               | —  |
| device  | Mobile | mobile.session              | `mobile_app_launch`                    | 打开应用                        | —  |
| device  | Mobile | mobile.session              | `mobile_app_open_and_jump`             | [公用]启动被测应用并跳转到指定界面          | —  |
| device  | Mobile | mobile.session              | `mobile_app_reset`                     | 重启应用                        | ✅  |
| device  | Mobile | mobile.session              | `mobile_app_reset_saveinfo`            | 重启被测应用(保存用户信息)              | ✅  |
| device  | Mobile | mobile.session              | `mobile_app_snapshot`                  | 截屏(wap)                     | —  |
| device  | Mobile | mobile.session              | `mobile_app_start`                     | 启动App                       | ✅  |
| device  | Mobile | mobile.session              | `mobile_browser_close`                 | 关闭浏览器(wap)                  | —  |
| device  | Mobile | mobile.session              | `mobile_browser_locate`                | 浏览器地址输入(wap)                | —  |
| device  | Mobile | mobile.session              | `mobile_browser_open`                  | 打开浏览器(wap)                  | —  |
| device  | Mobile | mobile.session              | `mobile_commActionTouch`               | 安卓九宫格解锁(通用)                 | —  |
| device  | Mobile | mobile.session              | `mobile_define_slip_for_element`       | [公用]自定义滚动屏幕至目标控件            | —  |
| device  | Mobile | mobile.session              | `mobile_define_swipe_direction`        | 自定义起止位置按方向滑屏(mobile/wap)    | —  |
| device  | Mobile | mobile.session              | `mobile_get_current_url`               | 获取当前url(wap)                | —  |
| device  | Mobile | mobile.session              | `mobile_get_device_ip`                 | 获取Android WIFI IP地址(mobile) | —  |
| device  | Mobile | mobile.session              | `mobile_longclick`                     | [公用]长按操作                    | —  |
| device  | Mobile | mobile.session              | `mobile_move_to_element`               | 移动屏幕至目标控件(wap)              | —  |
| device  | Mobile | mobile.session              | `mobile_presskey`                      | 物理按键                        | —  |
| device  | Mobile | mobile.session              | `mobile_set_network`                   | 设置网络连接状态                    | —  |
| device  | Mobile | mobile.session              | `mobile_slip_for_element`              | [公用]滚动屏幕至目标控件               | —  |
| device  | Mobile | mobile.session              | `mobile_swipe_direction`               | [公用]按方向滑屏                   | —  |
| device  | Mobile | mobile.session              | `mobile_tap`                           | 点击某个坐标(mobile)              | —  |
| device  | Mobile | mobile.session              | `mobile_tap_auto`                      | 坐标兼容点击(mobile)              | —  |
| device  | Mobile | mobile.session              | `native_web_swith_context`             | 切换移动上下文(h5/wap)             | —  |
| device  | Mobile | mobile.session              | `performance_data_capture`             | 性能数据捕获                      | —  |
| device  | WebUI  | web.browser                 | `web_browser_activate`                 | 浏览器激活                       | —  |
| device  | WebUI  | web.browser                 | `web_browser_addCookie`                | 增加cookie                    | —  |
| device  | WebUI  | web.browser                 | `web_browser_addCookie_Complex`        | 增加cookie(多配置)               | —  |
| device  | WebUI  | web.browser                 | `web_browser_back`                     | 浏览器后退                       | —  |
| device  | WebUI  | web.browser                 | `web_browser_click_alert`              | 弹框点击操作                      | —  |
| device  | WebUI  | web.browser                 | `web_browser_close`                    | 关闭当前浏览器                     | —  |
| device  | WebUI  | web.browser                 | `web_browser_close_andSwitch`          | 浏览器关闭并切换到原始窗口               | —  |
| device  | WebUI  | web.browser                 | `web_browser_deleteAllCookies`         | 删除所有cookies                 | —  |
| device  | WebUI  | web.browser                 | `web_browser_deleteCookieNamed`        | 删除某个cookie                  | —  |
| device  | WebUI  | web.browser                 | `web_browser_execute_js`               | 执行JS脚本                      | —  |
| device  | WebUI  | web.browser                 | `web_browser_forward`                  | 浏览器前进                       | —  |
| device  | WebUI  | web.browser                 | `web_browser_getBrowserTitle`          | 获取浏览器标题                     | ✅  |
| device  | WebUI  | web.browser                 | `web_browser_getBrowserType`           | 获取浏览器类型                     | —  |
| device  | WebUI  | web.browser                 | `web_browser_getCookieValueByName`     | 获取cookie的值                  | —  |
| device  | WebUI  | web.browser                 | `web_browser_getPageSource`            | 获取页面源码                      | —  |
| device  | WebUI  | web.browser                 | `web_browser_get_alertTxt`             | 获取弹框文本                      | —  |
| device  | WebUI  | web.browser                 | `web_browser_get_url`                  | 获取当前URL                     | ✅  |
| device  | WebUI  | web.browser                 | `web_browser_locate`                   | 浏览器地址输入                     | —  |
| device  | WebUI  | web.browser                 | `web_browser_maximize`                 | 浏览器最大化                      | —  |
| device  | WebUI  | web.browser                 | `web_browser_open`                     | 浏览器打开                       | ✅  |
| device  | WebUI  | web.browser                 | `web_browser_quit`                     | 退出浏览器                       | ✅  |
| device  | WebUI  | web.browser                 | `web_browser_refresh`                  | 浏览器刷新                       | —  |
| device  | WebUI  | web.browser                 | `web_browser_scroll_vertical_bar`      | 滚动条纵向移动                     | —  |
| device  | WebUI  | web.browser                 | `web_browser_set_promptValue`          | 输入弹框文本                      | —  |
| device  | WebUI  | web.browser                 | `web_browser_snapshot`                 | 浏览器截屏                       | —  |
| device  | WebUI  | web.browser                 | `web_browser_switch_frame`             | 浏览器页面框架切换                   | —  |
| device  | WebUI  | web.browser                 | `web_browser_switch_window`            | 浏览器窗口切换                     | —  |
| device  | WebUI  | web.browser                 | `web_browser_wait_alert`               | 等待弹框存在                      | —  |
| device  | WebUI  | web.browser                 | `web_browser_wait_for_exist`           | 等待控件存在性判断                   | —  |
| device  | WebUI  | web.browser                 | `web_browser_wait_for_text`            | 等待控件文本匹配性判断                 | —  |
| device  | WebUI  | web.browser                 | `web_browser_wait_for_visible`         | 等待控件可见性判断                   | —  |
| device  | WebUI  | web.element                 | `web_element_JSclick`                  | 控件JS点击                      | —  |
| device  | WebUI  | web.element                 | `web_element_check_click`              | 控件判断点击                      | —  |
| device  | WebUI  | web.element                 | `web_element_checkbox_click`           | 复选框点击                       | —  |
| device  | WebUI  | web.element                 | `web_element_click`                    | 点击元素                        | ✅  |
| device  | WebUI  | web.element                 | `web_element_click_and_switch`         | 控件点击并切至新打开窗口                | —  |
| device  | WebUI  | web.element                 | `web_element_combo_select`             | 下拉选择                        | —  |
| device  | WebUI  | web.element                 | `web_element_context_click`            | 控件右键点击                      | —  |
| device  | WebUI  | web.element                 | `web_element_double_click`             | 控件双击                        | —  |
| device  | WebUI  | web.element                 | `web_element_downloadFileAu3`          | 文件下载                        | —  |
| device  | WebUI  | web.element                 | `web_element_drag`                     | 鼠标拖拽                        | —  |
| device  | WebUI  | web.element                 | `web_element_drag_offset_forLogin`     | 登录页面安全滑块拖动                  | —  |
| device  | WebUI  | web.element                 | `web_element_get_element_Selected`     | 获取控件选择性                     | —  |
| device  | WebUI  | web.element                 | `web_element_get_element_attribute`    | 获取元素属性                      | ✅  |
| device  | WebUI  | web.element                 | `web_element_get_element_enabled`      | 获取控件可用性                     | —  |
| device  | WebUI  | web.element                 | `web_element_get_element_exist`        | 判断元素存在                      | ✅  |
| device  | WebUI  | web.element                 | `web_element_get_element_text`         | 获取元素文本                      | ✅  |
| device  | WebUI  | web.element                 | `web_element_get_element_visible`      | 获取控件可见性                     | ✅  |
| device  | WebUI  | web.element                 | `web_element_get_elements_number`      | 获取控件个数                      | —  |
| device  | WebUI  | web.element                 | `web_element_get_table_element`        | 获取表格中的控件文本                  | —  |
| device  | WebUI  | web.element                 | `web_element_mouseWheel`               | 鼠标滚轮滚动                      | —  |
| device  | WebUI  | web.element                 | `web_element_move`                     | 鼠标移动                        | —  |
| device  | WebUI  | web.element                 | `web_element_radio_click`              | 单选框点击                       | —  |
| device  | WebUI  | web.element                 | `web_element_safeElementInput`         | 安全控件文本框输入                   | —  |
| device  | WebUI  | web.element                 | `web_element_scroll_click`             | 控件滚动点击                      | —  |
| device  | WebUI  | web.element                 | `web_element_set_element_attribute`    | 设置控件属性值                     | —  |
| device  | WebUI  | web.element                 | `web_element_text_input`               | 输入文本                        | ✅  |
| device  | WebUI  | web.element                 | `web_element_uploadFileAu3`            | 文件上传_其它                     | —  |
| device  | WebUI  | web.element                 | `web_element_uploadfile_common`        | 文件上传_普通                     | —  |
| device  | WebUI  | web.element                 | `web_key_press`                        | 键盘动作                        | —  |
| device  | WebUI  | web.element                 | `web_key_press_WihtSelenium`           | 键盘动作(Selenium)              | —  |
| device  | WebUI  | web.element                 | `web_puzzle_drag_offset`               | 控件滑动                        | —  |
| device  | WebUI  | web.element                 | `web_puzzle_drag_offset_forLogin`      | 登录页面安全拼图拖动                  | —  |
| device  | WebUI  | web.element                 | `web_text_check_Input`                 | 文本框判断输入                     | —  |
| device  | WebUI  | web.verify                  | `common_ie_ua_linux`                   | IE伪装操作支付密码控件                | —  |
| device  | WebUI  | web.verify                  | `web_browser_killAll`                  | 浏览器进程清除                     | —  |
| device  | WebUI  | web.verify                  | `web_set_alert_text`                   | 校验弹出框文本(保存校验结果)             | —  |
| device  | WebUI  | web.verify                  | `web_set_combo_select_status`          | 校验下拉选项文本(保存校验结果)            | —  |
| device  | WebUI  | web.verify                  | `web_set_current_url_status`           | 校验当前页面URL(保存校验结果)           | —  |
| device  | WebUI  | web.verify                  | `web_set_element_attribute_status`     | 校验控件属性值(保存校验结果)             | —  |
| device  | WebUI  | web.verify                  | `web_set_element_enabled_status`       | 校验控件可用性(保存校验结果)             | —  |
| device  | WebUI  | web.verify                  | `web_set_element_existed_status`       | 校验控件是否存在(保存校验结果)            | —  |
| device  | WebUI  | web.verify                  | `web_set_element_selected_status`      | 校验控件是否已选中(保存校验结果)           | —  |
| device  | WebUI  | web.verify                  | `web_set_element_text_status`          | 校验控件文本(保存校验结果)              | —  |
| device  | WebUI  | web.verify                  | `web_set_element_visible_status`       | 校验控件可见性(保存校验结果)             | —  |
| device  | WebUI  | web.verify                  | `web_verify_alert_text`                | 校验弹出框文本                     | —  |
| device  | WebUI  | web.verify                  | `web_verify_combo_select`              | 校验下拉选项文本                    | —  |
| device  | WebUI  | web.verify                  | `web_verify_current_url`               | 校验当前页面URL                   | —  |
| device  | WebUI  | web.verify                  | `web_verify_element_attribute`         | 校验控件属性值                     | —  |
| device  | WebUI  | web.verify                  | `web_verify_element_enabled`           | 校验控件可用性                     | —  |
| device  | WebUI  | web.verify                  | `web_verify_element_existed`           | 校验控件是否存在                    | —  |
| device  | WebUI  | web.verify                  | `web_verify_element_selected`          | 校验控件是否已选中                   | —  |
| device  | WebUI  | web.verify                  | `web_verify_element_text`              | 校验控件文本                      | —  |
| device  | WebUI  | web.verify                  | `web_verify_element_visible`           | 校验控件可见性                     | —  |
| pure    | Http   | http.json_keywords          | `json_add_json_value`                  | 增加JSON元素内容                  | —  |
| pure    | Http   | http.json_keywords          | `json_comp`                            | JSON全量校验                    | —  |
| pure    | Http   | http.json_keywords          | `json_delete_json_value`               | 删除JSON元素内容                  | —  |
| pure    | Http   | http.json_keywords          | `json_exist_key`                       | 判断JSON中是否存在指定节点             | ✅  |
| pure    | Http   | http.json_keywords          | `json_exist_key_byjsonpath`            | 判断JSON节点存在(JsonPath)        | ✅  |
| pure    | Http   | http.json_keywords          | `json_get_Strs_Xkey_Value`             | 获取JSON某数组的子节点元素值            | —  |
| pure    | Http   | http.json_keywords          | `json_get_Strs_Xkey_Value_ByJsonPath`  | 获取JSON某数组的子节点元素值(JSONPATH)  | —  |
| pure    | Http   | http.json_keywords          | `json_get_json_value`                  | 获取JSON元素内容                  | ✅  |
| pure    | Http   | http.json_keywords          | `json_get_json_value_byjsonpath`       | 获取JSON值(JsonPath)           | ✅  |
| pure    | Http   | http.json_keywords          | `json_get_json_values_num`             | 获取JSON属性值数                  | ✅  |
| pure    | Http   | http.json_keywords          | `json_get_json_values_num_byjsonpath`  | 获取JSON属性值数(JSONPATH)        | ✅  |
| pure    | Http   | http.json_keywords          | `json_load_json_file`                  | 加载JSON文件                    | —  |
| pure    | Http   | http.json_keywords          | `json_load_json_file_fastjson`         | 加载JSON文件                    | —  |
| pure    | Http   | http.json_keywords          | `json_set_json_value`                  | 修改JSON元素内容                  | —  |
| pure    | Http   | http.json_keywords          | `json_set_json_value_byjsonpath`       | 修改JSON元素内容(JSONPATH)        | —  |
| pure    | Http   | http.json_keywords          | `json_to_string`                       | JSON对象转字符串                  | ✅  |
| pure    | Http   | http.json_keywords          | `json_verify_json_value`               | 校验JSON元素内容                  | ✅  |
| pure    | Http   | http.json_keywords          | `json_verify_json_value_ByJsonPath`    | 校验JSON值(JsonPath)           | ✅  |
| pure    | Http   | http.xml_keywords           | `xml_add_xml_value`                    | 增加XML元素节点                   | —  |
| pure    | Http   | http.xml_keywords           | `xml_copy`                             | 复制XML文件                     | —  |
| pure    | Http   | http.xml_keywords           | `xml_doc2_str`                         | 转换XML对象为字符串                 | —  |
| pure    | Http   | http.xml_keywords           | `xml_get_xml_nodeNum`                  | 获取XML元素个数                   | ✅  |
| pure    | Http   | http.xml_keywords           | `xml_get_xml_value`                    | 获取XML值(XPath)               | ✅  |
| pure    | Http   | http.xml_keywords           | `xml_load_xml_body`                    | 加载XML报文                     | —  |
| pure    | Http   | http.xml_keywords           | `xml_load_xml_file`                    | 加载XML文件                     | —  |
| pure    | Http   | http.xml_keywords           | `xml_set_xml_attr_value`               | 修改XML元素属性                   | —  |
| pure    | Http   | http.xml_keywords           | `xml_set_xml_value`                    | 修改XML元素内容                   | —  |
| pure    | Http   | http.xml_keywords           | `xml_verify_xml_All`                   | 全量校验XML内容                   | —  |
| pure    | Http   | http.xml_keywords           | `xml_verify_xml_Existed`               | 校验XML元素存在性                  | —  |
| pure    | Http   | http.xml_keywords           | `xml_verify_xml_value`                 | 校验XML值(XPath)               | ✅  |
| pure    | Http   | http.xml_keywords           | `xml_write`                            | 写入XML文件                     | —  |
| pure    | Public | builtin                     | `log`                                  | 日志输出                        | ✅  |
| pure    | Public | builtin                     | `set_var`                              | 设置变量                        | ✅  |
| pure    | Public | builtin                     | `verify_contains`                      | 校验包含                        | ✅  |
| pure    | Public | builtin                     | `verify_equals`                        | 校验相等                        | ✅  |
| pure    | Public | public.common               | `URLcode`                              | URL编码/解码                    | —  |
| pure    | Public | public.common               | `base64加密`                             | base64加密                    | —  |
| pure    | Public | public.common               | `base64解密`                             | base64解密                    | —  |
| pure    | Public | public.common               | `common_CSVFile_create`                | 生成并保存数据至CSV文件               | ✅  |
| pure    | Public | public.common               | `common_compare_str_length`            | 校验字符串长度                     | —  |
| pure    | Public | public.common               | `common_convert_time_format`           | 时间格式转换                      | —  |
| pure    | Public | public.common               | `common_create_RandomNum`              | 字符串随机生成                     | —  |
| pure    | Public | public.common               | `common_data_between`                  | 数值范围校验                      | —  |
| pure    | Public | public.common               | `common_data_calc`                     | 数值计算                        | ✅  |
| pure    | Public | public.common               | `common_data_compare`                  | 数值比较                        | ✅  |
| pure    | Public | public.common               | `common_excel_delRow`                  | 删除excel中某行                  | —  |
| pure    | Public | public.common               | `common_excel_editCellValue`           | 修改excel单元格值                 | —  |
| pure    | Public | public.common               | `common_excel_readCellValue`           | 读取excel单元格值                 | ✅  |
| pure    | Public | public.common               | `common_excel_writeCellValue`          | excel单元格写入值                 | ✅  |
| pure    | Public | public.common               | `common_generate_empty_str`            | 生成指定长度空字符串                  | ✅  |
| pure    | Public | public.common               | `common_generate_timestamp`            | 生成当前时间戳字符                   | —  |
| pure    | Public | public.common               | `common_get_36UID`                     | 获取uuid(36位)                 | —  |
| pure    | Public | public.common               | `common_get_EmailAddress`              | 邮箱地址随机生成                    | —  |
| pure    | Public | public.common               | `common_get_LocalHost_IPAddress`       | 获取本机IP地址                    | —  |
| pure    | Public | public.common               | `common_get_TelephoneNumber`           | 手机号码随机生成                    | —  |
| pure    | Public | public.common               | `common_get_current_millis`            | 获取当前毫秒时间戳                   | —  |
| pure    | Public | public.common               | `common_get_str_length`                | 获取字符串长度                     | ✅  |
| pure    | Public | public.common               | `common_get_timestamp`                 | 生成指定时间戳字符串                  | —  |
| pure    | Public | public.common               | `common_get_timestamp_fromDate`        | 从Date格式字符串生成Date数据          | —  |
| pure    | Public | public.common               | `common_get_timestamp_ms`              | 生成指定时间戳字符串(支持毫秒)            | —  |
| pure    | Public | public.common               | `common_get_url_element`               | 获取URL元素内容                   | —  |
| pure    | Public | public.common               | `common_reset_terminal_Type`           | 取消测试终端类型设置                  | —  |
| pure    | Public | public.common               | `common_set_terminal_Type`             | 测试终端类型手工设置                  | —  |
| pure    | Public | public.common               | `common_split_AndGetLength`            | 分割字符串并获取长度                  | ✅  |
| pure    | Public | public.common               | `common_split_AndGetValue`             | 分割字符串并获取列值                  | ✅  |
| pure    | Public | public.common               | `common_sreplace_Str`                  | 字符串替换                       | ✅  |
| pure    | Public | public.common               | `common_string_case_transform`         | 字符串大小写转换                    | ✅  |
| pure    | Public | public.common               | `common_subString_BetweenBeginAndEnd`  | 截取从指定开始位至结束位间的字符串           | ✅  |
| pure    | Public | public.common               | `common_subString_ByBegin`             | 截取从指定位开始至末尾的全部字符            | —  |
| pure    | Public | public.common               | `common_subString_ByLength`            | 截取从指定位开始及长度的字符串             | ✅  |
| pure    | Public | public.common               | `common_trim_str`                      | 字符串截空                       | ✅  |
| pure    | Public | public.common               | `common_verify_String`                 | 字符串校验                       | ✅  |
| pure    | Public | public.common               | `common_verify_file_existed`           | 校验文件是否存在                    | —  |
| pure    | Public | public.common               | `compare_ImageXY`                      | 图片对比                        | —  |
| pure    | Public | public.common               | `df_define_metadata`                   | 定义业务元数据                     | —  |
| pure    | Public | public.common               | `exec_control_multiple`                | 多结果校验(与)                    | —  |
| pure    | Public | public.common               | `exec_set_control_multiple`            | 获取与结果                       | —  |
| pure    | Public | public.common               | `form_compare`                         | 校验URL元素内容                   | —  |
| pure    | Public | public.common               | `getMd5`                               | MD5加密                       | ✅  |
| pure    | Public | public.common               | `id_card_creat`                        | 生成身份证号                      | —  |
| pure    | Public | public.common               | `logPrint`                             | 日志打印                        | —  |
| pure    | Public | public.common               | `ommon_pic_checkPicIsExisted`          | 获取页面图片原址请求响应码               | —  |
| pure    | Public | public.common               | `read_file`                            | 读取文件内容                      | —  |
| pure    | Public | public.common               | `roundValue`                           | 四舍五入                        | ✅  |
| pure    | Public | public.common               | `setVariable`                          | 自定义变量                       | —  |
| pure    | Public | public.common               | `web_common_sleep`                     | 等待时间                        | —  |
| pure    | WebUI  | web.image                   | `img_element_click`                    | 图像点击                        | ✅  |
| pure    | WebUI  | web.image                   | `img_element_doubleClick`              | 图像双击                        | —  |
| pure    | WebUI  | web.image                   | `img_element_exists`                   | 图像存在判断                      | ✅  |
| pure    | WebUI  | web.image                   | `img_element_rightClick`               | 图像右键                        | —  |
| pure    | WebUI  | web.image                   | `img_element_type`                     | 图像处输入                       | —  |
| pure    | WebUI  | web.image                   | `img_element_wait`                     | 等待图像出现                      | —  |
| pure    | WebUI  | web.image                   | `img_element_waitVanish`               | 等待图像消失                      | —  |
| service | Http   | data.elasticsearch_keywords | `es_query_log`                         | WindQ消息日志查询                 | —  |
| service | Http   | data.kafka_keywords         | `produceKafkaMsg`                      | 发送Kafka消息(文件)               | ✅  |
| service | Http   | data.kafka_keywords         | `readHeadTailMsg`                      | 读取最新/旧的Kafka消息              | —  |
| service | Http   | data.kafka_keywords         | `readKafkaMsg`                         | 读取指定offset的消息               | —  |
| service | Http   | http.client                 | `http_add_cookie`                      | 添加cookie                    | —  |
| service | Http   | http.client                 | `http_add_header`                      | 添加请求头                       | ✅  |
| service | Http   | http.client                 | `http_cleanMock`                       | 清除桩                         | ✅  |
| service | Http   | http.client                 | `http_delete`                          | 发送DELETE请求                  | —  |
| service | Http   | http.client                 | `http_get`                             | 发送GET请求                     | ✅  |
| service | Http   | http.client                 | `http_getCookieValue_BycookieName`     | 获取Cookie值                   | —  |
| service | Http   | http.client                 | `http_get_download`                    | HTTP_GET下载请求                | ✅  |
| service | Http   | http.client                 | `http_post`                            | 发送POST请求                    | ✅  |
| service | Http   | http.client                 | `http_post_Multipart`                  | HTTP文件上传                    | ✅  |
| service | Http   | http.client                 | `http_post_mock`                       | HTTP_POST请求(mock)           | ✅  |
| service | Http   | http.client                 | `http_put`                             | 发送PUT请求                     | —  |
| service | Http   | http.client                 | `http_remove_header`                   | 删除头域                        | —  |
| service | Http   | http.client                 | `http_setMock`                         | 埋桩                          | ✅  |
| service | Http   | http.client                 | `http_setproxy`                        | 定义http代理                    | —  |
| service | Http   | http.client                 | `http_verify_header`                   | 校验头域                        | —  |
| service | Http   | http.session                | `http_session_begin`                   | 开启HTTP会话                    | ✅  |
| service | Http   | http.session                | `http_session_end`                     | 关闭HTTP会话                    | ✅  |
| service | Http   | http.client                 | `http_patch`                           | 发送PATCH请求                   | ✅  |
| service | Http   | http.client                 | `http_head`                            | 发送HEAD请求                    | ✅  |
| service | Http   | http.client                 | `http_options`                         | 发送OPTIONS请求                 | ✅  |
| service | Http   | http.auth                   | `http_set_auth_basic`                  | 设置Basic认证                   | —  |
| service | Http   | http.auth                   | `http_set_auth_bearer`                 | 设置Bearer令牌                  | ✅  |
| service | Http   | http.auth                   | `http_set_auth_apikey`                 | 设置API Key                   | ✅  |
| pure    | Http   | http.assert_kw              | `http_assert_status`                   | 断言HTTP状态码                   | ✅  |
| pure    | Http   | http.assert_kw              | `http_assert_time_lt`                  | 断言响应时间小于                    | ✅  |
| pure    | Http   | http.assert_kw              | `http_assert_body_contains`            | 断言响应体包含                     | ✅  |
| pure    | Http   | http.assert_kw              | `json_assert_schema`                   | 断言JSON Schema               | ✅  |
| pure    | Http   | http.env                    | `api_env_use`                          | 切换API环境                     | ✅  |
| service | Public | data.database               | `database_close`                       | 关闭数据库连接                     | ✅  |
| service | Public | data.database               | `database_executeNoneQueSQL_HIVE`      | 执行非查询SQL(Hive)              | —  |
| service | Public | data.database               | `database_executeQueSQL_GETCOUNT_HIVE` | 执行查询SQL并获取行数(Hive)          | —  |
| service | Public | data.database               | `database_executeQueSQL_HIVE`          | 执行查询SQL并获取结果内容(Hive)        | —  |
| service | Public | data.database               | `database_get_data`                    | 获取结果集数据                     | ✅  |
| service | Public | data.database               | `database_get_rowcount`                | 获取结果集行数                     | ✅  |
| service | Public | data.database               | `database_non_query`                   | 执行非查询SQL                    | ✅  |
| service | Public | data.database               | `database_non_query_FromFile`          | 批量执行SQL                     | —  |
| service | Public | data.database               | `database_open`                        | 打开数据库连接                     | ✅  |
| service | Public | data.database               | `database_query`                       | 执行查询SQL                     | ✅  |
| service | Public | data.database               | `database_verify_data`                 | 校验数据库结果集                    | —  |
| service | Public | data.database               | `database_verify_rowCount`             | 校验数据库结果行数                   | —  |
| service | Public | data.elasticsearch_keywords | `es_query_dsl`                         | ES查询:QueryDSL               | ✅  |
| service | Public | data.ftp                    | `ftp_ftpclient_closeFtp`               | 关闭FTP                       | ✅  |
| service | Public | data.ftp                    | `ftp_ftpclient_connect`                | 连接FTP                       | ✅  |
| service | Public | data.ftp                    | `ftp_ftpclient_downloadFile`           | 下载文件                        | ✅  |
| service | Public | data.ftp                    | `ftp_ftpclient_uploadFile`             | 上传文件                        | ✅  |
| service | Public | data.hbase_keywords         | `hbase_connect`                        | 配置HBase数据库连接                | ✅  |
| service | Public | data.hbase_keywords         | `hbase_del`                            | 执行HBase单行删除操作               | —  |
| service | Public | data.hbase_keywords         | `hbase_get`                            | 执行HBase单行查询操作               | ✅  |
| service | Public | data.hbase_keywords         | `hbase_put`                            | 执行HBase单行新增操作               | ✅  |
| service | Public | data.hbase_keywords         | `hbase_verify_cell_existed`            | 校验HBase单行查询结果               | —  |
| service | Public | data.hbase_keywords         | `hbase_verify_table_existed`           | 校验HBase中表是否存在               | —  |
| service | Public | data.redis_keywords         | `redis_connect_redis`                  | 连接Redis                     | ✅  |
| service | Public | data.redis_keywords         | `redis_del_RedisKey`                   | 删除Redis键                    | ✅  |
| service | Public | data.redis_keywords         | `redis_del_RedisKeyFromFile`           | 批量删除redis中key               | —  |
| service | Public | data.redis_keywords         | `redis_del_RedisKey_withResult`        | 删除redis中key数据并返回结果          | —  |
| service | Public | data.redis_keywords         | `redis_del_RedisScoredSet`             | 删除redis中key对应的有序集合member    | —  |
| service | Public | data.redis_keywords         | `redis_get_RedisHashVal`               | 获取redis中对应key的哈希域值          | —  |
| service | Public | data.redis_keywords         | `redis_get_RedisList`                  | 获取redis中对应key的List集合        | —  |
| service | Public | data.redis_keywords         | `redis_get_RedisSet`                   | 获取redis中对应key的set集合值        | —  |
| service | Public | data.redis_keywords         | `redis_get_RedisSortedSet`             | 获取redis中对应key的有序集合值         | —  |
| service | Public | data.redis_keywords         | `redis_get_RedisSortedSetScore`        | 获取redis中对应key的有序集合值的权重      | —  |
| service | Public | data.redis_keywords         | `redis_get_RedisVal`                   | 获取Redis值                    | ✅  |
| service | Public | data.redis_keywords         | `redis_get_key_ttl`                    | 获取redis中对应key的剩余生存时间        | —  |
| service | Public | data.redis_keywords         | `redis_get_keys`                       | 获取redis中匹配key               | —  |
| service | Public | data.redis_keywords         | `redis_quit_Redis`                     | 断开Redis                     | ✅  |
| service | Public | data.redis_keywords         | `redis_set_RedisHsh`                   | 设置redis中Hash数据              | —  |
| service | Public | data.redis_keywords         | `redis_set_RedisList`                  | 设置redis中list数据              | —  |
| service | Public | data.redis_keywords         | `redis_set_RedisSet`                   | 设置redis中set数据               | —  |
| service | Public | data.redis_keywords         | `redis_set_RedisString`                | 设置Redis字符串                  | ✅  |
| service | Public | data.redis_keywords         | `redis_set_ScoredSet`                  | 设置redis中有序集合数据              | —  |
| service | Public | data.redis_keywords         | `redis_verify_KeysNum`                 | 校验redis中匹配key个数             | —  |
| service | Public | data.ssh                    | `linux_ssh_close`                      | 关闭SSH                       | ✅  |
| service | Public | data.ssh                    | `linux_ssh_connect`                    | 连接SSH                       | ✅  |
| service | Public | data.ssh                    | `linux_ssh_runCmd_WithResult`          | 执行命令(取结果)                   | ✅  |
| service | Public | data.ssh                    | `linux_ssh_runCmd_WithoutResult`       | 执行命令(不取结果)                  | —  |
| service | Public | data.ssh                    | `linux_ssh_sftp_fileDownload`          | SFTP文件下载                    | —  |
| service | Public | data.ssh                    | `linux_ssh_sftp_fileUpload`            | SFTP文件上传                    | —  |
