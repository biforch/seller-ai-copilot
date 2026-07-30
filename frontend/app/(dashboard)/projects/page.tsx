'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Plus } from 'lucide-react';

import { useProjects } from '@/hooks/useProjects';


export default function ProjectsPage() {

  const router = useRouter();


  const {
    projects,
    isLoading,
    fetchProjects,
  } = useProjects();



  useEffect(() => {

    fetchProjects();

  }, [fetchProjects]);



  return (

    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">


      <div className="flex justify-between items-center mb-8">


        <div>

          <h1 className="text-3xl font-bold text-gray-900">
            My Projects
          </h1>

          <p className="text-gray-600 mt-1">
            Manage your AI selling projects
          </p>

        </div>



        <button
          onClick={() =>
            router.push('/projects/create')
          }
          className="
          flex
          items-center
          gap-2
          px-4
          py-2
          bg-blue-600
          text-white
          rounded-lg
          hover:bg-blue-700
          "
        >

          <Plus className="w-5 h-5"/>

          New Project

        </button>


      </div>





      {
        isLoading ? (

          <p className="text-gray-500">
            Loading...
          </p>


        ) : projects.length === 0 ? (


          <div
            className="
            bg-white
            border
            rounded-xl
            p-8
            text-center
            "
          >

            <p className="text-gray-500 mb-4">
              No projects yet
            </p>


            <button
              onClick={() =>
                router.push('/projects/create')
              }
              className="
              px-4
              py-2
              bg-blue-600
              text-white
              rounded-lg
              "
            >

              Create your first project

            </button>


          </div>



        ) : (



          <div
            className="
            grid
            md:grid-cols-3
            gap-5
            "
          >


            {
              projects.map(project => (


                <div
                  key={project.id}
                  onClick={() =>
                    router.push(
                      `/projects/${project.id}`
                    )
                  }
                  className="
                  bg-white
                  border
                  rounded-xl
                  p-6
                  cursor-pointer
                  hover:shadow-md
                  transition
                  "
                >


                  <h2 className="font-semibold text-lg">

                    {project.name}

                  </h2>


                  <div className="mt-3 text-sm text-gray-500">

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


                  </div>


                </div>


              ))
            }


          </div>


        )

      }



    </div>

  );

}