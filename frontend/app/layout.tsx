import type { Metadata } from "next";
import "./globals.css";
import { Toaster } from "@/components/ui/toaster";

export const metadata: Metadata = {
    title: "SellerAI Copilot - AI-Powered eCommerce Assistant",
    description: "Generate optimized product listings for Amazon and Shopify with AI",
};

export default function RootLayout({
                                       children,
                                   }: Readonly<{
    children: React.ReactNode;
}>) {
    return (
        <html lang="en">
        <body className="font-sans">
        {children}
        <Toaster />
        </body>
        </html>
    );
}
