'use client';

import { useEffect } from 'react';

import { useRouter } from 'next/navigation';

import {
  FileSearch,
  FolderKanban,
  History
} from 'lucide-react';


import { useProducts } from '@/hooks/useProducts';

import { useProjects } from '@/hooks/useProjects';
import { LISTING_AUDIT_INTERNAL_VISIBLE } from '@/lib/feature-flags';



export default function DashboardPage() {


  const router = useRouter();



  const {
    products,
    isLoading: productsLoading,
    fetchProducts,
  } = useProducts();



  const {
    projects,
    isLoading: projectsLoading,
    fetchProjects: loadProjects,
  } = useProjects();




  useEffect(()=>{


    fetchProducts({ page: 1, page_size: 5 });

    loadProjects({ page: 1, page_size: 5 });



  },[
    fetchProducts,
    loadProjects
  ]);





  return (

<div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">


<div className="mb-8">

<h1 className="text-3xl font-bold text-gray-900">
Dashboard
</h1>


<p className="text-gray-600 mt-1">
Manage your AI selling projects and listings
</p>


</div>





<div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8">

{LISTING_AUDIT_INTERNAL_VISIBLE ? (
<button
onClick={()=>router.push('/listing-audit')}
className="bg-blue-600 text-white p-6 rounded-xl hover:bg-blue-700 flex items-center gap-4"
>
<FileSearch/>
<div>
<h3 className="font-semibold">Listing Audit</h3>
<p className="text-sm">Review a listing before publishing</p>
</div>
</button>
) : null}



<button
onClick={()=>router.push('/projects')}
className="
bg-purple-600
text-white
p-6
rounded-xl
hover:bg-purple-700
flex
items-center
gap-4
"
>


<FolderKanban/>


<div>

<h3 className="font-semibold">
Projects
</h3>


<p className="text-sm">
Manage selling projects
</p>


</div>


</button>

<button
onClick={()=>router.push('/products')}
className="
bg-white
border
p-6
rounded-xl
hover:shadow-md
flex
items-center
gap-4
"
>


<History/>


<div>

<h3 className="font-semibold">
Products
</h3>


<p className="text-sm text-gray-500">
View products
</p>


</div>


</button>



</div>






<div className="bg-white rounded-xl border p-6 mb-8">


<h2 className="text-lg font-semibold mb-4">
Recent Projects
</h2>




{
projectsLoading ?

<p>
Loading...
</p>


:

projects.length===0?


<p className="text-gray-500">
No projects yet.
</p>


:

<div className="space-y-3">


{
projects.map(project=>(


<div
key={project.id}
onClick={()=>router.push(`/projects/${project.id}`)}
className="
flex
justify-between
items-center
p-3
rounded-lg
hover:bg-gray-50
cursor-pointer
"
>


<div>

<p className="font-medium">
{project.name}
</p>


<p className="text-sm text-gray-500">

{project.platform}
{" • "}
{project.market}

</p>


</div>


<span className="text-sm text-gray-400">
Project
</span>


</div>


))
}



</div>


}



</div>







<div className="bg-white rounded-xl border p-6">


<h2 className="text-lg font-semibold mb-4">
Recent Products
</h2>



{
productsLoading ?

<p>
Loading...
</p>


:

products.length===0?


<p className="text-gray-500">
No products yet.
</p>


:


<div className="space-y-3">


{
products.map(product=>(


<div
key={product.id}
onClick={()=>router.push(`/products/${product.id}`)}
className="
flex
justify-between
items-center
p-3
rounded-lg
hover:bg-gray-50
cursor-pointer
"
>


<div>

<p className="font-medium">
{product.name}
</p>


<p className="text-sm text-gray-500">

{product.category || "Uncategorized"}

{" • "}

{product.platform}

</p>


</div>



<span className="text-sm text-gray-400">

{product.generations_count || 0}

{" generations"}

</span>


</div>


))
}


</div>


}



</div>



</div>


  );

}
