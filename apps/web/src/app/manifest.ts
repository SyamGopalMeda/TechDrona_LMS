import type { MetadataRoute } from "next";

/** Web app manifest; icons and colours match the Tech Drona website (tech drona/dist/site.webmanifest). */
export default function manifest(): MetadataRoute.Manifest {
  const name = process.env.NEXT_PUBLIC_APP_NAME ?? "Tech Drona";
  return {
    name,
    short_name: name,
    start_url: "/app",
    display: "standalone",
    theme_color: "#032269",
    background_color: "#f4f6fa",
    icons: [
      { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" },
    ],
  };
}
