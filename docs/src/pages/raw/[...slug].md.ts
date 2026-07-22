import type { APIRoute, GetStaticPaths } from "astro";
import { getCollection } from "astro:content";

// Serve each doc page's markdown source at /raw/<slug>.md so the
// "Copy page as Markdown" control can fetch it. Build-time only; no runtime.
export const getStaticPaths: GetStaticPaths = async () => {
  const docs = await getCollection("docs");
  return docs
    .filter((doc) => doc.id !== "index")
    .map((doc) => ({
      params: { slug: doc.id },
      props: {
        body: `# ${doc.data.title}\n\n${doc.body ?? ""}`,
      },
    }));
};

export const GET: APIRoute = ({ props }) => {
  return new Response(props.body as string, {
    headers: { "Content-Type": "text/markdown; charset=utf-8" },
  });
};
