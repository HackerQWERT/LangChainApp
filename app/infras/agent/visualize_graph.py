import sys
import os
import base64
import urllib.request
import urllib.error

# 确保能导入 app 模块
sys.path.append(os.getcwd())


def generate_svg(mermaid_code, output_path):
    """通过 Mermaid Ink API 生成 SVG"""
    print(f"🎨 正在请求 Mermaid Ink API 生成 SVG...")

    # 1. Base64 编码 Mermaid 文本
    graphbytes = mermaid_code.encode("utf8")
    base64_bytes = base64.b64encode(graphbytes)
    base64_string = base64_bytes.decode("ascii")

    # 2. 构造 SVG 请求 URL
    url = "https://mermaid.ink/svg/" + base64_string

    # 3. 下载并保存
    try:
        req = urllib.request.Request(
            url, headers={'User-Agent': 'Python-LangGraph-Client'})
        with urllib.request.urlopen(req) as response:
            data = response.read()
            with open(output_path, "wb") as f:
                f.write(data)
        print(f"✅ SVG 已保存: {os.path.abspath(output_path)}")
        return True
    except urllib.error.HTTPError as e:
        print(f"❌ SVG 生成失败 (HTTP {e.code}): URL可能过长或API暂时不可用。")
        return False
    except Exception as e:
        print(f"❌ SVG 生成发生错误: {e}")
        return False


def main():
    from app.infras.agent import travel_agent

    print("🎨 正在生成 LangGraph 结构图...")

    try:
        # 1. 获取图对象
        graph = travel_agent.get_graph()

        # 2. 生成 Mermaid 语法文本 (作为备份查看方式)
        print("\n--- Mermaid Syntax (可复制到 https://mermaid.live 查看) ---")
        mermaid_txt = graph.draw_mermaid()
        print(mermaid_txt)
        print("-----------------------------------------------------------\n")

        # 保存 Mermaid 文本到 txt 文件
        txt_file = "agent_workflow.txt"
        with open(txt_file, "w", encoding="utf-8") as f:
            f.write(mermaid_txt)
        print(f"✅ TXT 已保存: {os.path.abspath(txt_file)}")

        # 3. 生成 SVG (新增功能)
        svg_file = "agent_workflow.svg"
        generate_svg(mermaid_txt, svg_file)

        # 4. 生成 PNG 图片
        # draw_mermaid_png() 默认会调用 Mermaid Ink 的 API 生成图片二进制流
        print(f"🎨 正在生成 PNG 预览...")
        png_data = graph.draw_mermaid_png()

        output_file = "agent_workflow.png"
        with open(output_file, "wb") as f:
            f.write(png_data)

        print(f"✅ PNG 已保存: {os.path.abspath(output_file)}")
        print(f"   请在左侧文件列表中打开 {output_file} 或 {svg_file} 查看实际结构。")

    except Exception as e:
        print(f"❌ 生成失败: {e}")
        print("提示: 如果是网络错误，请尝试复制上面的 Mermaid Syntax 到在线编辑器查看。")


if __name__ == "__main__":
    main()
