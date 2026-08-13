export function GeneratePageFallback() {
  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">AI Generate</h1>
        <p className="text-gray-500 mt-2">Loading...</p>
      </div>
      <div className="bg-white border rounded-xl p-8 text-center text-gray-400">
        Preparing generate workspace...
      </div>
    </div>
  );
}
