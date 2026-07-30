'use client';

import { useState } from 'react';

import { MARKETS, PLATFORMS } from '@/lib/constants';
import type { GenerateFormData } from '@/types';


interface ProductFormProps {

  data: GenerateFormData;

  onChange: (
    data: GenerateFormData
  ) => void;

  onSubmit: () => void;

  isLoading?: boolean;

  submitLabel?: string;

}



export function ProductForm({

  data,

  onChange,

  onSubmit,

  isLoading = false,

  submitLabel = 'Generate Listing',

}: ProductFormProps) {



  const update = (
    field: keyof GenerateFormData,
    value: string
  ) => {


    onChange({

      ...data,

      [field]: value,

    });


  };


  // Keep the raw text the user is typing separately from the parsed
  // array. If we derive the input's displayed value straight from
  // data.advantages (join(', ')) every keystroke round-trips through
  // split -> trim -> join, which silently eats the trailing space you
  // just typed before starting the next word/phrase.
  const [advantagesText, setAdvantagesText] = useState(
    (data.advantages || []).join(', ')
  );


  const updateAdvantages = (
    value: string
  ) => {

    setAdvantagesText(value);

    onChange({

      ...data,

      advantages: value
        .split(',')
        .map(v => v.trim())
        .filter(Boolean),

    });

  };





  return (


    <form

      onSubmit={(e)=>{

        e.preventDefault();

        onSubmit();

      }}

      className="space-y-4"

    >



      {
        data.project_id ? (

          <div
            className="
            bg-purple-50
            text-purple-700
            px-3
            py-2
            rounded-lg
            text-sm
            "
          >

            Project attached

          </div>

        ) : (

          <div
            className="
            bg-amber-50
            text-amber-700
            px-3
            py-2
            rounded-lg
            text-sm
            "
          >

            Select a project above before generating

          </div>

        )
      }






      <div>


        <label className="
        block
        text-sm
        font-medium
        text-gray-700
        mb-1
        ">

          Product Name

        </label>



        <input


          type="text"


          value={data.name}


          onChange={(e)=>
            update(
              'name',
              e.target.value
            )
          }



          className="
          w-full
          px-4
          py-2
          border
          rounded-lg
          focus:ring-2
          focus:ring-blue-500
          outline-none
          "



          placeholder="Wireless Bluetooth Earbuds"



          required


        />


      </div>







      <div>


        <label className="
        block
        text-sm
        font-medium
        text-gray-700
        mb-1
        ">


          Category


        </label>




        <input


          type="text"


          value={data.category}


          onChange={(e)=>
            update(
              'category',
              e.target.value
            )
          }



          className="
          w-full
          px-4
          py-2
          border
          rounded-lg
          focus:ring-2
          focus:ring-blue-500
          outline-none
          "



          placeholder="Electronics > Audio"



          required


        />



      </div>




      <div>

        <label className="
        block
        text-sm
        font-medium
        text-gray-700
        mb-1
        ">

          Target Customer
          <span className="text-gray-400 font-normal"> (optional)</span>

        </label>

        <input

          type="text"

          value={data.target_customer || ''}

          onChange={(e)=>
            update(
              'target_customer',
              e.target.value
            )
          }

          className="
          w-full
          px-4
          py-2
          border
          rounded-lg
          focus:ring-2
          focus:ring-blue-500
          outline-none
          "

          placeholder="e.g. young professionals"

        />

      </div>




      <div>

        <label className="
        block
        text-sm
        font-medium
        text-gray-700
        mb-1
        ">

          Key Advantages
          <span className="text-gray-400 font-normal"> (optional, comma-separated)</span>

        </label>

        <input

          type="text"

          value={advantagesText}

          onChange={(e)=>
            updateAdvantages(e.target.value)
          }

          className="
          w-full
          px-4
          py-2
          border
          rounded-lg
          focus:ring-2
          focus:ring-blue-500
          outline-none
          "

          placeholder="e.g. noise cancellation, long battery life"

        />

      </div>




      <div className="
      grid
      grid-cols-2
      gap-4
      ">



        <div>


          <label className="
          block
          text-sm
          font-medium
          text-gray-700
          mb-1
          ">


            Platform


          </label>




          <select


            value={data.platform}


            onChange={(e)=>
              update(
                'platform',
                e.target.value
              )
            }



            className="
            w-full
            px-4
            py-2
            border
            rounded-lg
            "


          >


            {
              PLATFORMS.map(platform=>(


                <option
                  key={platform}
                  value={platform}
                >

                  {platform}

                </option>


              ))
            }



          </select>


        </div>








        <div>


          <label className="
          block
          text-sm
          font-medium
          text-gray-700
          mb-1
          ">


            Market


          </label>




          <select


            value={data.market}


            onChange={(e)=>
              update(
                'market',
                e.target.value
              )
            }




            className="
            w-full
            px-4
            py-2
            border
            rounded-lg
            "


          >



            {
              MARKETS.map(market=>(


                <option

                  key={market}

                  value={market}

                >

                  {market}


                </option>


              ))
            }



          </select>


        </div>



      </div>








      <button


        type="submit"


        disabled={isLoading || !data.project_id}



        className="
        w-full
        py-2.5
        bg-blue-600
        text-white
        font-medium
        rounded-lg
        hover:bg-blue-700
        disabled:opacity-50
        "


      >



        {
          isLoading

          ?

          'Generating...'

          :

          submitLabel

        }




      </button>




    </form>


  );

}