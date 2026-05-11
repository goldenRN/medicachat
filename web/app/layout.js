import "./globals.css";

export const metadata = {
  title: "SOS Medica AI Chatbot",
  description: "SOS Medica Mongolia document-aware assistant",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
    apple: "/profile.jpg",
  },
};

export default function RootLayout({ children }) {
  return (
    <html lang="mn">
      <body>{children}</body>
    </html>
  );
}
