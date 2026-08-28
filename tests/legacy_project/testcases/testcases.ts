<?xml version="1.0" encoding="UTF-8"?>
<root ver="1.0" db_id="suite001" need_update="false" tag="WEB">
  <before>
    <step id="web_browser_open" comment="套件前置-启动浏览器" isrun="true">
      <param id="url">${baseUrl}</param>
      <param id="type">Chrome</param>
    </step>
  </before>
  <after>
    <step id="web_browser_quit" comment="套件后置-退出" isrun="true"/>
  </after>
  <fault/>
  <datapool>DATATABLE(NONE,true)</datapool>
</root>
