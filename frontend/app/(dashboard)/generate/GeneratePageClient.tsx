'use client';


import { useState, useEffect } from 'react';

import { useRouter, useSearchParams } from 'next/navigation';


import { AnalyzerResultView } from '@/components/features/AnalyzerResult';

import { ListingResultView } from '@/components/features/ListingResult';

import { ProductForm } from '@/components/features/ProductForm';


import { useGenerate } from '@/hooks/useGenerate';

import { useProjects } from '@/hooks/useProjects';


import type {
  AnalyzeFormData,
  GenerateFormData
} from '@/types';



type Tab =
  | 'generate'
  | 'analyze';





export function GeneratePageClient(){


  const router = useRouter();

  const searchParams =
    useSearchParams();


  const {
    projects,
    isLoading: projectsLoading,
    fetchProjects,
  } = useProjects();


  useEffect(()=>{

    fetchProjects({ page_size: 100 });

  },[fetchProjects]);



  const projectId =
    searchParams.get(
      'project_id'
    );




  const [
    tab,
    setTab
  ] = useState<Tab>(
    'generate'
  );




  const [
    formData,
    setFormData
  ] = useState<GenerateFormData>({

    project_id:
      projectId || undefined,

    name:'',

    category:'',

    market:'USA',

    platform:'Amazon'

  });





  const [
    analyzeData,
    setAnalyzeData
  ] = useState<AnalyzeFormData>({

    project_id:
      projectId || undefined,

    title:'',

    reviews:0,

    rating:4,

    description:''

  });





  /*
   * URL project_id变化时同步
   */

  useEffect(()=>{


    setFormData(prev=>({

      ...prev,

      project_id:
        projectId || undefined

    }));


    setAnalyzeData(prev=>({

      ...prev,

      project_id:
        projectId || undefined

    }));


  },[projectId]);






  const {

    isLoading,

    error,

    listingResult,

    analyzeResult,

    generateListing,

    analyzeListing,

    reset


  } = useGenerate();







  const handleGenerate =
    async()=>{


      await generateListing(
        formData
      );


    };







  const handleAnalyze =
    async()=>{


      await analyzeListing(
        analyzeData
      );


    };









  return (

    <div
      className="
      max-w-7xl
      mx-auto
      px-4
      py-8
      "
    >



      <div className="mb-8">


        <h1
          className="
          text-3xl
          font-bold
          text-gray-900
          "
        >

          AI Generate

        </h1>



        <div className="mt-3 max-w-sm">

          <label className="block text-sm text-gray-600 mb-1">
            Project
          </label>

          <select

            value={projectId || ''}

            onChange={(e)=>{

              const value = e.target.value;

              router.replace(
                value
                ? `/generate?project_id=${value}`
                : '/generate'
              );

            }}

            className="
            w-full
            border
            rounded-lg
            px-3
            py-2
            bg-white
            "

          >

            <option value="" disabled>
              {
                projectsLoading
                ? 'Loading projects...'
                : 'Select a project'
              }
            </option>

            {
              projects.map(p=>(

                <option key={p.id} value={p.id}>
                  {p.name}
                </option>

              ))
            }

          </select>

          {
            !projectsLoading &&
            projects.length === 0 &&

            <p className="text-sm text-amber-600 mt-2">
              You don&apos;t have any projects yet.{' '}
              <button
                type="button"
                onClick={()=>router.push('/projects/create')}
                className="underline"
              >
                Create one
              </button>
              {' '}before generating.
            </p>
          }

        </div>


      </div>







      <div
        className="
        flex
        gap-3
        mb-6
        "
      >


        <button

          onClick={()=>{

            setTab('generate');

            reset();

          }}

          className={

            `
            px-4
            py-2
            rounded-lg
            font-medium

            ${
              tab==='generate'
              ?
              'bg-blue-600 text-white'
              :
              'bg-white border'
            }

            `
          }


        >

          Generate Listing

        </button>





        <button


          onClick={()=>{


            setTab('analyze');

            reset();


          }}


          className={

            `
            px-4
            py-2
            rounded-lg
            font-medium

            ${
              tab==='analyze'
              ?
              'bg-blue-600 text-white'
              :
              'bg-white border'
            }

            `
          }


        >

          Analyze Competitor

        </button>



      </div>







      {
        error &&


        <div

          className="
          bg-red-50
          text-red-600
          rounded-lg
          p-3
          mb-5
          "

        >

          {error}


        </div>

      }









      <div

        className="
        grid
        lg:grid-cols-2
        gap-8
        "

      >





        <div

          className="
          bg-white
          border
          rounded-xl
          p-6
          "

        >



        {
          tab==='generate'


          ?


          <ProductForm


            data={formData}


            onChange={setFormData}


            onSubmit={handleGenerate}


            isLoading={isLoading}


          />



          :



          <form


            onSubmit={(e)=>{

              e.preventDefault();

              handleAnalyze();

            }}


            className="
            space-y-5
            "

          >




            <div>

              <label className="block text-sm mb-1">

                Competitor Title

              </label>


              <input


                value={
                  analyzeData.title
                }


                onChange={
                  e=>
                  setAnalyzeData({

                    ...analyzeData,

                    title:e.target.value

                  })
                }


                className="
                w-full
                border
                rounded-lg
                px-4
                py-2
                "

                required


              />


            </div>






            <div
              className="
              grid
              grid-cols-2
              gap-4
              "
            >


              <div>


                <label className="block text-sm mb-1">

                  Reviews

                </label>



                <input

                  type="number"


                  value={
                    analyzeData.reviews
                  }


                  onChange={
                    e=>
                    setAnalyzeData({

                      ...analyzeData,

                      reviews:
                        Number(e.target.value)

                    })
                  }


                  className="
                  w-full
                  border
                  rounded-lg
                  px-4
                  py-2
                  "

                />


              </div>





              <div>


                <label className="block text-sm mb-1">

                  Rating

                </label>



                <input

                  type="number"

                  step="0.1"

                  max="5"

                  value={
                    analyzeData.rating
                  }


                  onChange={
                    e=>
                    setAnalyzeData({

                      ...analyzeData,

                      rating:
                      Number(e.target.value)

                    })
                  }


                  className="
                  w-full
                  border
                  rounded-lg
                  px-4
                  py-2
                  "

                />


              </div>


            </div>







            <div>


              <label className="block text-sm mb-1">

                Description

              </label>



              <textarea


                value={
                  analyzeData.description
                }


                onChange={
                  e=>
                  setAnalyzeData({

                    ...analyzeData,

                    description:e.target.value

                  })
                }



                className="
                w-full
                border
                rounded-lg
                px-4
                py-2
                h-32
                "


              />


            </div>







            <button

              disabled={isLoading || !projectId}


              className="
              w-full
              bg-blue-600
              text-white
              py-2.5
              rounded-lg
              disabled:opacity-50
              "

            >

              {
                isLoading
                ?
                'Analyzing...'
                :
                !projectId
                ?
                'Select a project first'
                :
                'Analyze'
              }


            </button>



          </form>



        }



        </div>









        <div>


          {
            listingResult &&


            <ListingResultView

              result={
                listingResult
              }

            />

          }






          {
            analyzeResult &&


            <AnalyzerResultView

              result={
                analyzeResult
              }

            />

          }





          {
            !listingResult &&
            !analyzeResult &&


            <div

              className="
              bg-white
              border
              rounded-xl
              p-8
              text-center
              text-gray-400
              "

            >

              Result will appear here


            </div>


          }




        </div>






      </div>





    </div>


  );

}