import { APP_NAME } from '@/lib/constants';

export function Footer() {
  return (
    <footer className="border-t bg-white mt-auto">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 text-center text-sm text-gray-500">
        &copy; {new Date().getFullYear()} {APP_NAME}. AI-powered eCommerce Assistant.
      </div>
    </footer>
  );
}
