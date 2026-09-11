/**
 * 一个组件抛异常，不该让整站变成一屏白。
 *
 * **白屏是最坏的失败方式**：它不告诉你哪里坏了、是不是网断了、要不要刷新，
 * 也不留下任何可以拿去查的东西。实际发生过一次——接口少返回一个数组字段，
 * 某一行拿 `undefined.length`，整个 /stocks/tasks 一片空白。
 * React 的默认行为就是这样：没有边界，一处抛错就卸载整棵树。
 *
 * 所以这里只做三件事，一件不多：
 * 1. 说清楚坏的是这一页，不是你的数据；
 * 2. 把错误原文摆出来——报错原文是唯一能直接拿去查的东西，藏起来只会让人去猜；
 * 3. 给一个"重新加载"，因为多数情况刷一下就过去了。
 *
 * 不做自动重试：一直抛错的组件重试只会闪烁，还把真正的原因刷掉。
 */

import { Component, type ErrorInfo, type ReactNode } from "react";

type State = { error: Error | null; where: string };

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null, where: "" };

  static getDerivedStateFromError(error: Error): State {
    return { error, where: "" };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // 留在控制台：边界吞掉异常之后，控制台就是唯一还能看到完整调用栈的地方
    console.error("页面渲染出错：", error, info.componentStack);
    // **组件栈要显示在页面上，不能只留在控制台。**
    // 第一版只写了报错信息，结果拿到「Cannot read properties of undefined
    // (reading 'toFixed')」——这句话对定位毫无帮助，全站有几十处 toFixed，
    // 而线上数据跟本地不一样，照着代码一个个看是猜不出来的。
    // 让报错自己说出它在哪个组件里，比任何猜测都快。
    this.setState({ where: (info.componentStack || "").trim() });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="crash-page">
        <h1>这一页没能显示出来</h1>
        <p>
          出错的是页面，不是你的数据。刷新一次通常就好；反复出现就把下面这行发给我。
        </p>
        <pre>{this.state.error.message || String(this.state.error)}</pre>
        {this.state.where && <details className="crash-where">
          <summary>出错的位置（把这一段一起发给我）</summary>
          {/* 只取前 12 层：再往下都是框架自己的包装层，对定位没有帮助 */}
          <pre>{this.state.where.split("\n").slice(0, 12).join("\n")}</pre>
        </details>}
        <p className="crash-path">页面：{window.location.pathname}</p>
        <button className="page-action" onClick={() => window.location.reload()}>
          重新加载
        </button>
      </div>
    );
  }
}
