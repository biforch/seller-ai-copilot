import type { Metadata } from "next";
import "./globals.css";
import { Toaster } from "@/components/ui/toaster";

export const metadata: Metadata = {
    metadataBase: new URL("https://listnara.com"),
    title: "Amazon Listing Audit Tool | Listnara",
    description: "Find what your Amazon listing fails to explain before you rewrite it.",
    applicationName: "Listnara",
    keywords: ["Amazon listing audit", "Amazon listing optimization", "listing quality", "Amazon seller tool"],
    robots: { index: true, follow: true },
    openGraph: {
        title: "Amazon Listing Audit Tool | Listnara",
        description: "Evidence-backed listing audits for Amazon sellers.",
        url: "https://listnara.com",
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
