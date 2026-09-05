import type { Metadata } from "next";
import "./globals.css";
import { Toaster } from "@/components/ui/toaster";
import { PUBLIC_SITE_URL } from "@/lib/site-url";

export const metadata: Metadata = {
    metadataBase: new URL(PUBLIC_SITE_URL),
    title: "Amazon Listing Audit Tool | Listnara",
    description: "Audit your Amazon listing for buyer clarity, information gaps, conversion readiness, and search coverage. Get evidence-backed issues and prioritized actions.",
    applicationName: "Listnara",
    keywords: ["Amazon listing audit", "Amazon listing optimization", "listing quality", "Amazon seller tool"],
    robots: { index: true, follow: true },
    openGraph: {
        title: "Amazon Listing Audit Tool | Listnara",
        description: "Evidence-backed listing audits for Amazon sellers.",
        url: PUBLIC_SITE_URL,
        siteName: "Listnara",
        type: "website",
    },
    twitter: { card: "summary_large_image", title: "Amazon Listing Audit Tool | Listnara", description: "Find what your Amazon listing fails to explain before you rewrite it." },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
    return (
        <html lang="en">
        <body className="font-sans">
        {children}
        <Toaster />
        </body>
        </html>
    );
}

