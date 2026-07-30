'use client';


import {
  useEffect,
  useState
} from 'react';


import {
  useParams,
  useRouter
} from 'next/navigation';


import {
  apiClient
} from '@/app/api/client';


import type {
  ProjectDetail
} from '@/types';



export default function ProjectDetailPage(){


  const params = useParams();

  const router = useRouter();


  const id = params.id as string;



  const [
    project,
    setProject
  ] = useState<ProjectDetail|null>(null);


  const [
    error,
    setError
  ] = useState<string|null>(null);


  const [
    isLoading,
    setIsLoading
  ] = useState(true);




  useEffect(()=>{


    async function load(){


      setIsLoading(true);

      setError(null);


      try{


        const data =
          await apiClient.get<ProjectDetail>(
            `/projects/${id}`
          );


        setProject(data);


      }catch(err){


        setError(
          err instanceof Error
          ? err.message
          : 'Failed to load project'
        );


      }finally{


        setIsLoading(false);


      }


    }



    if(id){

      load();

    }


  },[id]);




  if(isLoading){

    return (

      <div className="p-8">
        Loading...
      </div>

    );

  }


  if(error || !project){

    return (

      <div className="p-8 text-red-600">
        {error || 'Project not found.'}
      </div>

    );

  }




  return (

    <div className="
      max-w-5xl
      mx-auto
      px-4
      py-8
    ">


      <div className="
        bg-white
        border
        rounded-xl
        p-8
      ">


        <div className="flex items-start justify-between">

          <div>

            <h1 className="
              text-3xl
              font-bold
            ">

              {project.name}

            </h1>


            {
              project.description &&

              <p className="text-gray-500 mt-1">
                {project.description}
              </p>
            }

          </div>


          <span className="
            px-3
            py-1
            rounded-full
            text-xs
            font-medium
            bg-gray-100
            text-gray-700
            capitalize
          ">

            {project.status || 'active'}

          </span>

        </div>



        <div className="
          mt-4
          text-gray-600
          space-y-2
        ">


          <p>

            Platform:
            {' '}
            {project.platform}

          </p>


          <p>

            Market:
            {' '}
            {project.market}

          </p>


          <p>

            Products:
            {' '}
            {project.product_count ?? project.products.length}

          </p>


        </div>




        <button

          onClick={()=>
            router.push(
              `/generate?project_id=${project.id}`
            )
          }


          className="
            mt-8
            px-5
            py-3
            bg-blue-600
            text-white
            rounded-lg
            hover:bg-blue-700
          "

        >

          Generate Listing

        </button>


      </div>



      <div className="
        bg-white
        border
        rounded-xl
        p-8
        mt-6
      ">

        <h2 className="text-lg font-semibold mb-4">
          Products
        </h2>

        {
          project.products.length === 0 ? (

            <p className="text-gray-500">
              No products yet — generate a listing to add one.
            </p>

          ) : (

            <div className="divide-y">

              {
                project.products.map(p=>(

                  <button
                    key={p.id}
                    onClick={()=>router.push(`/products/${p.id}`)}
                    className="
                      w-full
                      flex
                      items-center
                      justify-between
                      py-3
                      text-left
                      hover:bg-gray-50
                      px-2
                      rounded-lg
                    "
                  >

                    <div>

                      <p className="font-medium text-gray-900">
                        {p.name}
                      </p>

                      <p className="text-sm text-gray-500">
                        {p.category || 'Uncategorized'} • {p.platform} • {p.market}
                      </p>

                    </div>

                    <span className="text-sm text-gray-400">
                      {p.generations_count} generation{p.generations_count === 1 ? '' : 's'}
                    </span>

                  </button>

                ))
              }

            </div>

          )
        }

      </div>


    </div>

  );


}
