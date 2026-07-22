// @ts-check
import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";

/**
 * Wrap every <table> in <div class="table-scroll"> so wide tables scroll
 * horizontally inside the content column instead of squishing their cells.
 * Hand-rolled tree walk — no extra dependency.
 */
function rehypeWrapTables() {
  const wrap = (node) => {
    if (!node || !Array.isArray(node.children)) return;
    for (let i = 0; i < node.children.length; i++) {
      const child = node.children[i];
      if (child.type === "element" && child.tagName === "table") {
        node.children[i] = {
          type: "element",
          tagName: "div",
          properties: { className: ["table-scroll"] },
          children: [child],
        };
      } else {
        wrap(child);
      }
    }
  };
  return (tree) => wrap(tree);
}

// https://astro.build/config
export default defineConfig({
  site: "https://ml-dev-hub.github.io",
  base: "/csv_trans",
  markdown: {
    rehypePlugins: [rehypeWrapTables],
  },
  devToolbar: { enabled: false },
  integrations: [
    starlight({
      title: "csv-trans",
      // Header branding is rendered by the SiteTitle component override.
      customCss: ["./src/styles/custom.css"],
      components: {
        PageTitle: "./src/components/PageTitle.astro",
        SiteTitle: "./src/components/SiteTitle.astro",
      },
      expressiveCode: {
        // Near-monochrome syntax themes so code sits with the page instead of
        // fighting it; chrome flattened to hairline borders on the page tokens.
        themes: ["min-dark", "min-light"],
        // Shell one-liners render as plain code, not a fake terminal window.
        defaultProps: {
          overridesByLang: {
            "bash,sh,shell": { frame: "none" },
          },
        },
        styleOverrides: {
          borderRadius: "8px",
          borderColor: "var(--csv-border)",
          borderWidth: "1px",
          codeBackground: "var(--csv-code-bg)",
          codeFontFamily: "var(--sl-font-mono)",
          uiFontFamily: "var(--sl-font)",
          codeFontSize: "0.875rem",
          codeLineHeight: "1.65",
          codePaddingBlock: "0.875rem",
          codePaddingInline: "1.125rem",
          uiFontSize: "0.75rem",
          focusBorder: "var(--sl-color-text-accent)",
          frames: {
            shadowColor: "transparent",
            editorBackground: "var(--csv-code-bg)",
            editorActiveTabBackground: "var(--csv-code-bg)",
            editorActiveTabForeground: "var(--sl-color-gray-2)",
            editorActiveTabIndicatorTopColor: "transparent",
            editorActiveTabIndicatorBottomColor: "var(--sl-color-gray-4)",
            editorTabBarBackground: "var(--csv-surface)",
            editorTabBarBorderBottomColor: "var(--csv-border)",
            editorTabBorderRadius: "0",
            terminalBackground: "var(--csv-code-bg)",
            terminalTitlebarBackground: "var(--csv-surface)",
            terminalTitlebarBorderBottomColor: "var(--csv-border)",
            terminalTitlebarForeground: "var(--sl-color-gray-3)",
            terminalTitlebarDotsForeground: "var(--sl-color-gray-4)",
            terminalTitlebarDotsOpacity: "0.4",
            inlineButtonBorder: "transparent",
            inlineButtonBackground: "var(--sl-color-gray-4)",
          },
        },
      },
      favicon: "/favicon.svg",
      description:
        "Dependency-free CSV translation for Python: translate selected text columns while preserving structure exactly, with pluggable local and remote providers.",
      social: [
        {
          icon: "github",
          label: "GitHub",
          href: "https://github.com/ML-Dev-Hub/csv_trans",
        },
      ],
      editLink: {
        baseUrl: "https://github.com/ML-Dev-Hub/csv_trans/edit/main/docs/",
      },
      lastUpdated: true,
      sidebar: [
        { label: "Getting started", slug: "getting-started" },
        { label: "How it works", slug: "how-it-works" },
        { label: "Providers", slug: "providers" },
        { label: "Cookbooks", slug: "cookbooks" },
        { label: "Privacy & security", slug: "privacy-and-security" },
        {
          label: "Reference",
          items: [
            { label: "Overview", slug: "reference" },
            { label: "Python API", slug: "reference/python-api" },
            { label: "CLI", slug: "reference/cli" },
          ],
        },
      ],
    }),
  ],
});
