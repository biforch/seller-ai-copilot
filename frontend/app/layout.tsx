import type { Metadata } from "next";
import "./globals.css";
import { Toaster } from "@/components/ui/toaster";

export const metadata: Metadata = {
    title: "Amazon Listing Audit Tool | Listnara",
    description: "Find what your Amazon listing fails to explain before you rewrite it.",
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
